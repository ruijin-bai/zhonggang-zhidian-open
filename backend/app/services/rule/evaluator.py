"""Evaluate governed rules without delegating business conclusions to an LLM."""
from __future__ import annotations

from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import DecisionRuleStatus
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.services.permission.rbac import build_filter
from app.services.rule.evidence import load_rule_sources
from app.utils.metrics import ACTIVE_RULE_TOTAL, MANUAL_REVIEW_TOTAL, RULE_CONFLICT_TOTAL


def regulation_effective_filter(as_of: date):
    """Only currently effective regulations can support a live conclusion."""
    return and_(
        RegulationFile.status == "current",
        or_(RegulationFile.effective_date.is_(None), RegulationFile.effective_date <= as_of),
        or_(RegulationFile.expiry_date.is_(None), RegulationFile.expiry_date >= as_of),
    )


def _within_amount(rule: DecisionRule, amount_minor: int) -> bool:
    if rule.amount_min_minor is not None:
        if amount_minor < rule.amount_min_minor or (amount_minor == rule.amount_min_minor and not rule.min_inclusive):
            return False
    if rule.amount_max_minor is not None:
        if amount_minor > rule.amount_max_minor or (amount_minor == rule.amount_max_minor and not rule.max_inclusive):
            return False
    return True


def _conditions_match(required: dict, facts: dict) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for key, expected in (required or {}).items():
        if key not in facts or facts[key] in (None, "", []):
            missing.append(key)
            continue
        actual = facts[key]
        if isinstance(expected, list):
            if actual not in expected:
                return False, missing
        elif actual != expected:
            return False, missing
    return True, missing


class RuleEvaluationService:
    async def evaluate(
        self,
        session: AsyncSession,
        *,
        user,
        permissions,
        scenario: str,
        org_path: str,
        amount_minor: int | None,
        currency: str | None,
        facts: dict,
        as_of: date | None = None,
    ) -> dict:
        as_of = as_of or date.today()
        rows = await load_rule_sources(session, user, permissions, statuses=[DecisionRuleStatus.CURRENT.value], scenario=scenario, effective=True, require_authority=True, as_of=as_of)
        ACTIVE_RULE_TOTAL.set(len(rows))
        if not rows:
            MANUAL_REVIEW_TOTAL.labels(reason="no_active_rule").inc()
            return {
                "need_human": True,
                "risk_level": "high",
                "reason_code": "no_active_rule",
                "summary": "未找到当前有效且已启用的办理规则，不能生成制度结论，请提交人工复核。",
                "missing_fields": [],
                "approval_path": [],
                "materials": [],
                "evidence": [],
                "matched_rule_ids": [],
            }

        matched: list[tuple[DecisionRule, Clause, RegulationFile]] = []
        missing_fields: set[str] = set()
        for rule, clause, file in rows:
            if rule.effective_from and rule.effective_from > as_of:
                continue
            if rule.effective_to and rule.effective_to < as_of:
                continue
            scope = rule.org_scope.rstrip("/")
            if org_path != scope and not org_path.startswith(scope + "/"):
                continue
            currency_matches = rule.currency == "*" or rule.currency == currency
            if rule.currency != "*" and not currency:
                missing_fields.add("currency")
            if rule.amount_min_minor is not None or rule.amount_max_minor is not None:
                if amount_minor is None:
                    missing_fields.add("amount_minor")
                    continue
                if not _within_amount(rule, amount_minor):
                    continue
            if not currency_matches:
                continue
            conditions_ok, missing = _conditions_match(rule.conditions, facts)
            missing_fields.update(missing)
            if not conditions_ok or missing:
                continue
            matched.append((rule, clause, file))

        if not matched or missing_fields:
            if missing_fields:
                labels = {"amount_minor": "金额", "currency": "币种"}
                readable = "、".join(labels.get(item, item) for item in sorted(missing_fields))
                summary = f"尚缺少用于规则判断的字段：{readable}。补齐后可重新校验；当前不能生成审批结论。"
                reason_code = "missing_facts"
                risk = "medium"
            else:
                summary = "未命中适用规则，可能存在例外条件、规则缺口或权限限制，请提交人工复核。"
                reason_code = "no_matching_rule"
                risk = "high"
            MANUAL_REVIEW_TOTAL.labels(reason=reason_code).inc()
            return {
                "need_human": True,
                "risk_level": risk,
                "reason_code": reason_code,
                "summary": summary,
                "missing_fields": sorted(missing_fields),
                "approval_path": [],
                "materials": [],
                "evidence": [],
                "matched_rule_ids": [],
            }

        unique_paths = {tuple(rule.approver_path or []) for rule, _, _ in matched}
        ambiguous = len(unique_paths) > 1
        primary_rule, primary_clause, primary_file = matched[0]
        evidence = [
            {
                "rule_id": rule.rule_id,
                "file_id": file.file_id,
                "file_title": file.title,
                "file_version": file.version,
                "clause_id": clause.clause_id,
                "clause_no": clause.clause_no,
                "excerpt": clause.content[:500],
                "source_kind": rule.source_kind,
                "asset_version_id": rule.asset_version_id,
                "retrieval_unit_id": rule.retrieval_unit_id,
                "source_page": clause.source_page,
                "source_locator": clause.source_locator,
                "content_hash": clause.content_hash,
            }
            for rule, clause, file in matched
        ]
        if ambiguous:
            RULE_CONFLICT_TOTAL.inc()
            MANUAL_REVIEW_TOTAL.labels(reason="ambiguous_rules").inc()
            summary = "命中多条审批路径不一致的规则，系统不自动选择，请提交人工复核。"
            risk = "high"
        else:
            summary = "已按当前有效、已启用的制度规则生成办理路径；请按列示材料办理。"
            risk = "medium" if primary_rule.risk_note else "low"
        return {
            "need_human": ambiguous,
            "risk_level": risk,
            "reason_code": "ambiguous_rules" if ambiguous else "matched",
            "summary": summary,
            "missing_fields": [],
            "approval_path": primary_rule.approver_path or [],
            "materials": primary_rule.required_materials or [],
            "risk_note": primary_rule.risk_note,
            "evidence": evidence,
            "matched_rule_ids": [rule.rule_id for rule, _, _ in matched],
            "as_of": as_of.isoformat(),
        }
