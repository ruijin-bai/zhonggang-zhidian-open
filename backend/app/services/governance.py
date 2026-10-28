"""Evidence extraction and persistent governance-queue synchronization."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.clause import Clause
from app.db.models.governance_task import GovernanceTask
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.services.permission.rbac import build_filter
from app.services.rule.evaluator import regulation_effective_filter

SCENARIO_KEYWORDS = {
    "contract_change": ["合同", "变更", "索赔", "签订", "分包"],
    "payment": ["付款", "支付", "结算", "报销", "费用"],
    "procurement": ["采购", "招标", "供应商", "物资"],
    "safety": ["安全", "风险", "事故", "应急", "HSE"],
    "employment": ["员工", "用工", "招聘", "借调", "劳动合同", "薪酬"],
}

DOMAIN_KEYWORDS = {
    "安全": ["HSE", "安全", "应急", "职业健康", "环保", "质量事故"],
    "采购": ["采购", "招标", "供应商", "合作方", "分包单位", "物资装备"],
    "人事": ["员工", "人力资源", "薪酬", "绩效", "年金", "考勤", "休假", "招聘", "用工"],
    "财务": ["财务", "资金", "税务", "报销", "会计", "预算", "费用管理"],
    "合规": ["合规", "审计", "纪律", "问责", "违规", "风险管理"],
    "工程": ["工程", "项目管理", "施工", "EPC", "设计", "勘察"],
    "行政": ["品牌", "标识", "印章", "档案", "公文", "办公"],
}

_DATE_RE = re.compile(
    r"本(?:办法|规定|细则|制度|方案|条例|准则|手册)自\s*"
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*起?\s*(?:施行|执行|生效)"
)
_CODE_RE = re.compile(r"[\u4e00-\u9fffA-Za-z]{1,12}(?:发)?〔20\d{2}〕\d{1,5}号")
_AMOUNT_RE = re.compile(
    r"(?:人民币|美元|欧元|奈拉|CNY|RMB|USD|NGN)?\s*\d+(?:\.\d+)?\s*(?:亿元|万元|元|亿美元|万美元)"
    r"(?:以上|以下|以内|以外|至\s*\d+(?:\.\d+)?\s*(?:亿元|万元|元|亿美元|万美元))?",
    re.IGNORECASE,
)
_APPROVAL_RE = re.compile(r"[^。；\n]{0,50}(?:审批|审核|批准|审议|报批|备案)[^。；\n]{0,70}")
_MATERIAL_RE = re.compile(r"[^。；\n]{0,40}(?:材料|附件|报告|申请表|发票|合同)[^。；\n]{0,70}")


def metadata_missing_fields(item: RegulationFile) -> list[str]:
    missing: list[str] = []
    if not item.regulation_code or item.regulation_code.strip() == item.title.strip():
        missing.append("制度编码")
    if item.effective_date is None:
        missing.append("生效日期")
    if not item.owner_org:
        missing.append("责任部门")
    if not item.domain or item.domain == "*":
        missing.append("制度域")
    return missing


def _unique_matches(pattern: re.Pattern, text: str, limit: int = 5) -> list[str]:
    values: list[str] = []
    for match in pattern.finditer(text):
        value = re.sub(r"\s+", "", match.group(0)).strip()
        if value and value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def metadata_evidence(item: RegulationFile, clauses: list[Clause]) -> dict:
    """Return suggestions only when the stored source contains inspectable evidence."""
    body = "\n".join(clause.content or "" for clause in clauses)
    suggestions: dict[str, dict] = {}

    domain_hits = {
        domain: [word for word in words if word.lower() in item.title.lower()]
        for domain, words in DOMAIN_KEYWORDS.items()
    }
    domain_hits = {domain: hits for domain, hits in domain_hits.items() if hits}
    if domain_hits:
        ranked = sorted(domain_hits.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        if len(ranked) == 1 or len(ranked[0][1]) > len(ranked[1][1]):
            domain, hits = ranked[0]
            suggestions["domain"] = {
                "value": domain,
                "evidence": f"标题命中：{'、'.join(hits)}",
                "rule": "title_keyword_classification",
                "confidence": "high",
            }

    date_values: list[tuple[str, str, str]] = []
    for clause in clauses:
        for match in _DATE_RE.finditer(clause.content or ""):
            try:
                value = date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                continue
            evidence = re.sub(r"\s+", "", match.group(0))
            record = (value, clause.clause_id, f"{clause.clause_no}：{evidence}")
            if record not in date_values:
                date_values.append(record)
    unique_dates = sorted({record[0] for record in date_values})
    if len(unique_dates) == 1 and "汇编" not in item.title:
        record = next(row for row in date_values if row[0] == unique_dates[0])
        suggestions["effective_date"] = {
            "value": record[0], "clause_id": record[1], "evidence": record[2],
            "rule": "explicit_effective_date", "confidence": "high",
        }
    elif unique_dates:
        suggestions["effective_date_candidates"] = {
            "values": unique_dates[:10],
            "evidence": "原文存在多个日期或属于汇编，必须人工确认所属制度",
            "rule": "ambiguous_effective_dates",
            "confidence": "review_required",
        }

    title_codes = _unique_matches(_CODE_RE, item.title)
    body_codes = _unique_matches(_CODE_RE, body)
    if len(title_codes) == 1:
        suggestions["regulation_code"] = {
            "value": title_codes[0], "evidence": f"制度标题：{item.title}",
            "rule": "official_code_in_title", "confidence": "high",
        }
    elif body_codes:
        suggestions["regulation_code_candidates"] = {
            "values": body_codes, "evidence": "原文检出文号，需核对是否为本制度而非引用文件",
            "rule": "official_code_in_body", "confidence": "review_required",
        }
    return {"suggestions": suggestions, "source": "stored_clause_text", "generated_by": "deterministic_rules_v1"}


async def build_rule_candidates(db: AsyncSession, user, perms) -> list[dict]:
    governed_statuses = ["pending_review", "current"]
    anchored = set((await db.execute(
        select(DecisionRule.clause_id).where(DecisionRule.status.in_(governed_statuses))
    )).scalars().all())
    result: list[dict] = []
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        keyword_filter = or_(*[
            predicate for word in keywords for predicate in (
                Clause.content.ilike(f"%{word}%"), RegulationFile.title.ilike(f"%{word}%")
            )
        ])
        stmt = (
            select(Clause, RegulationFile)
            .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
            .where(
                Clause.status == "current", regulation_effective_filter(date.today()),
                build_filter(user, perms, Clause.secret_level), keyword_filter,
                Clause.clause_no.not_in(["全文", "正文"]), func.length(Clause.content) <= 4000,
            )
            .limit(200)
        )
        if anchored:
            stmt = stmt.where(Clause.clause_id.not_in(anchored))
        scored: list[tuple] = []
        for clause, regulation in (await db.execute(stmt)).all():
            text = f"{regulation.title} {clause.clause_no} {clause.content}"
            hits = [word for word in keywords if word.lower() in text.lower()]
            if not hits:
                continue
            title_hits = sum(word.lower() in regulation.title.lower() for word in keywords)
            tag_text = " ".join(clause.scenario_tags or [])
            tag_hits = sum(word.lower() in tag_text.lower() for word in keywords)
            score = len(hits) * 10 + title_hits * 2 + tag_hits * 5 - min(len(clause.content), 4000) / 4000
            scored.append((score, clause, regulation, hits))
        for score, clause, regulation, hits in sorted(scored, key=lambda row: -row[0])[:10]:
            content = clause.content or ""
            amounts = _unique_matches(_AMOUNT_RE, content)
            approvals = _unique_matches(_APPROVAL_RE, content, 3)
            materials = _unique_matches(_MATERIAL_RE, content, 3)
            currencies = [code for label, code in (
                ("人民币", "CNY"), ("CNY", "CNY"), ("RMB", "CNY"),
                ("美元", "USD"), ("USD", "USD"), ("奈拉", "NGN"), ("NGN", "NGN"),
            ) if label.lower() in content.lower()]
            result.append({
                "scenario": scenario, "file_id": regulation.file_id, "file_title": regulation.title,
                "clause_id": clause.clause_id, "clause_no": clause.clause_no,
                "excerpt": content[:500], "matched_keywords": hits, "score": round(score, 2),
                "requires_business_review": True,
                "evidence_signals": {
                    "amount_mentions": amounts, "currency_mentions": sorted(set(currencies)),
                    "approval_mentions": approvals, "material_mentions": materials,
                },
            })
    return result


async def sync_governance_tasks(db: AsyncSession, user, perms) -> dict:
    now = datetime.now(timezone.utc)
    existing = {
        task.task_key: task
        for task in (await db.execute(
            select(GovernanceTask)
            .join(RegulationFile, GovernanceTask.file_id == RegulationFile.file_id)
            .where(build_filter(user, perms))
        )).scalars().all()
    }
    files = list((await db.execute(
        select(RegulationFile).where(build_filter(user, perms)).order_by(RegulationFile.title)
    )).scalars().all())
    file_ids = [item.file_id for item in files]
    clauses_by_file: dict[str, list[Clause]] = defaultdict(list)
    if file_ids:
        for clause in (await db.execute(
            select(Clause).where(Clause.file_id.in_(file_ids), Clause.status == "current")
        )).scalars().all():
            clauses_by_file[clause.file_id].append(clause)

    created = updated = resolved = 0
    for item in files:
        key = f"metadata:{item.file_id}"
        missing = metadata_missing_fields(item)
        task = existing.get(key)
        if not missing:
            if task and task.status not in {"resolved", "dismissed"}:
                task.status, task.resolved_at = "resolved", now
                task.resolution_note = "制度元数据字段已完整"
                resolved += 1
            continue
        evidence = metadata_evidence(item, clauses_by_file[item.file_id])
        if task is None:
            task = GovernanceTask(
                task_key=key, task_type="regulation_metadata", file_id=item.file_id,
                title=f"补齐《{item.title}》元数据", status="open",
                priority="high" if item.status == "current" else "normal",
                missing_fields=missing, evidence=evidence,
            )
            db.add(task)
            existing[key] = task
            created += 1
        else:
            task.missing_fields, task.evidence = missing, evidence
            if task.status == "resolved":
                task.status, task.resolved_at, task.resolution_note = "open", None, None
            updated += 1

    candidates = await build_rule_candidates(db, user, perms)
    candidate_keys: set[str] = set()
    for item in candidates:
        key = f"rule:{item['scenario']}:{item['clause_id']}"
        candidate_keys.add(key)
        task = existing.get(key)
        evidence = {
            "file_title": item["file_title"], "clause_no": item["clause_no"],
            "excerpt": item["excerpt"], "matched_keywords": item["matched_keywords"],
            "signals": item["evidence_signals"], "generated_by": "deterministic_rules_v1",
        }
        review_fields = ["适用边界", "审批路径", "所需材料", "业务复核"]
        if task is None:
            task = GovernanceTask(
                task_key=key, task_type="rule_candidate", file_id=item["file_id"],
                clause_id=item["clause_id"], scenario=item["scenario"],
                title=f"结构化规则：{item['file_title']} {item['clause_no']}", status="open",
                priority="high" if item["evidence_signals"]["amount_mentions"] else "normal",
                missing_fields=review_fields, evidence=evidence,
            )
            db.add(task)
            existing[key] = task
            created += 1
        else:
            task.missing_fields, task.evidence = review_fields, evidence
            updated += 1

    anchored = set((await db.execute(
        select(DecisionRule.clause_id).where(DecisionRule.status.in_(["pending_review", "current"]))
    )).scalars().all())
    for task in existing.values():
        if task.task_type == "rule_candidate" and task.clause_id in anchored and task.status not in {"resolved", "dismissed"}:
            task.status, task.resolved_at = "resolved", now
            task.resolution_note = "该条款已形成待审核或现行规则"
            resolved += 1
    await db.commit()
    return {"created": created, "updated": updated, "resolved": resolved, "metadata_files": len(files), "rule_candidates": len(candidates)}
