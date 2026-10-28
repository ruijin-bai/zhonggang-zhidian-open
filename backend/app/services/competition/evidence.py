"""Competition evidence aggregation with explicit missing-data semantics."""
from __future__ import annotations

import ast
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.permission import Permission
from app.services.competition.scenarios import validate_competition_scenarios
from app.services.trial import build_trial_summary
from app.services.eval.business_golden import validate_golden_cases
from app.services.rule.evidence import load_rule_sources
from app.services.rule.evaluator import regulation_effective_filter

BACKEND_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_PATH = BACKEND_ROOT / "tests" / "golden_business_qa.json"
GOLDEN_RESULT_PATH = BACKEND_ROOT / "eval_golden_result.json"

AWARD_READINESS_THRESHOLDS = {
    "trial_participants": 20,
    "real_questions": 50,
    "benchmark_records": 30,
    "expert_reviewed_total": 30,
    "featured_scenarios_passed": 3,
    "verified_source_rules": 3,
}


def build_award_readiness(trial: dict, golden: dict, rule_coverage: dict) -> dict:
    """Translate evidence into explicit, non-inflatable competition gates."""
    definitions = [
        ("trial_participants", "真实试用人数", trial.get("trial_participants"), "试点组织人", "组织真实账号进入试用模式"),
        ("real_questions", "真实试用问题", trial.get("real_questions"), "试点组织人", "完成真实业务问题并保留反馈"),
        ("benchmark_records", "人工与AI配对计时", trial.get("benchmark_records"), "试点组织人", "同题分别完成人工和AI计时"),
        ("expert_reviewed_total", "业务专家签审金标", golden.get("expert_reviewed_total"), "制度责任人", "签审问题、答案、条款和数字边界"),
        ("featured_scenarios_passed", "精品场景闭环", rule_coverage.get("featured_scenarios_passed"), "制度责任人+审核骨干", "完成制度、规则、事项和版本影响闭环"),
        ("verified_source_rules", "权威来源现行规则", rule_coverage.get("verified_source_rules"), "制度责任人+审核骨干", "补齐权威元数据并审核发布规则"),
    ]
    items = []
    for key, label, current, owner, action in definitions:
        value = int(current or 0)
        target = AWARD_READINESS_THRESHOLDS[key]
        items.append({
            "key": key,
            "label": label,
            "current": value,
            "target": target,
            "passed": value >= target,
            "owner": owner,
            "action": action,
        })
    passed = sum(item["passed"] for item in items)
    return {
        "passed_total": passed,
        "gate_total": len(items),
        "all_passed": passed == len(items),
        "items": items,
        "disclaimer": "门槛仅判断真实证据是否达到最低样本量，不替代业务部门验收或评委评分。",
    }


def migration_source_info() -> dict:
    revisions: dict[str, tuple[str, ...]] = {}
    for path in sorted((BACKEND_ROOT / "alembic" / "versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        values[target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        down = values.get("down_revision")
        if not isinstance(revision, str):
            continue
        parents = () if down is None else (down,) if isinstance(down, str) else tuple(down)
        revisions[revision] = parents
    parent_ids = {parent for parents in revisions.values() for parent in parents}
    roots = sorted(key for key, parents in revisions.items() if not parents)
    heads = sorted(set(revisions) - parent_ids)
    return {"revision_count": len(revisions), "roots": roots, "heads": heads, "single_root_single_head": len(roots) == 1 and len(heads) == 1}


def golden_evidence() -> dict:
    try:
        cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8")) if GOLDEN_PATH.exists() else []
    except (ValueError, OSError):
        cases = []
    if not isinstance(cases, list):
        cases = []
    id_counts = Counter(case.get("id") for case in cases if isinstance(case, dict) and isinstance(case.get("id"), str))
    signed = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or id_counts.get(case["id"], 0) != 1:
            continue
        if not isinstance(case.get("reviewer"), str) or not case["reviewer"].strip() or not isinstance(case.get("reviewed_at"), str):
            continue
        try:
            reviewed = date.fromisoformat(case["reviewed_at"])
            errors = validate_golden_cases([case])
        except (ValueError, TypeError, AttributeError, KeyError):
            continue
        if reviewed.isoformat() != case["reviewed_at"] or reviewed > date.today() or errors:
            continue
        if not isinstance(case.get("facts"), dict) or not isinstance(case.get("expected_need_human"), bool):
            continue
        if not all(isinstance(case.get(field), list) for field in ["expected_sources", "expected_claims", "expected_numbers"]):
            continue
        if not all(isinstance(value, str) and value.strip() for field in ["expected_claims", "expected_numbers"] for value in case[field]):
            continue
        if not all(isinstance(source, dict) and all(isinstance(source.get(key), str) and source[key].strip() for key in ["regulation_code", "clause_no"]) for source in case["expected_sources"]):
            continue
        if not all(isinstance(case.get(field), str) and case[field].strip() for field in ["question", "category"]):
            continue
        if case.get("expected_answer_mode") not in {"authoritative", "clarify", "refuse", "manual_review"}:
            continue
        signed.append(case)
    dataset_hash = hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    result = None
    if GOLDEN_RESULT_PATH.exists():
        try:
            candidate = json.loads(GOLDEN_RESULT_PATH.read_text(encoding="utf-8"))
            details = candidate.get("details", [])
            detail_ids = [row.get("id") for row in details if isinstance(row, dict) and isinstance(row.get("id"), str)]
            if (signed and len(signed) == len(cases)
                and candidate.get("dataset") == "golden_business_qa"
                and candidate.get("metric_scope") == "business_answer_quality"
                and candidate.get("golden_dataset_sha256") == dataset_hash
                and candidate.get("expert_reviewed_total") == len(signed)
                and len(detail_ids) == len(signed)
                and set(detail_ids) == {case["id"] for case in signed}):
                result = candidate
        except (ValueError, TypeError, AttributeError, OSError):
            pass
    return {
        "expert_reviewed_total": len(signed),
        "registered_case_total": len(cases),
        "unsigned_or_invalid_total": len(cases) - len(signed),
        "golden_dataset_sha256": dataset_hash,
        "result_available": result is not None,
        "metrics": ({key: value for key, value in result.items() if key not in {"details"}} if result else None),
        "disclaimer": "仅计题目完整、唯一编号及审核人/有效审核日期字段齐备的记录，仍需原始业务签审佐证。评测结果必须匹配当前题集校验值和全部编号；不匹配时为空。",
    }


async def build_competition_evidence(db: AsyncSession) -> dict:
    trial = await build_trial_summary(db)
    scenarios = await validate_competition_scenarios(db)
    regulation_current = int((await db.execute(select(func.count()).select_from(RegulationFile).where(regulation_effective_filter(date.today())))).scalar() or 0)
    clause_current = int((await db.execute(select(func.count()).select_from(Clause).where(Clause.status == "current"))).scalar() or 0)
    # Competition evidence is the R4 operational aggregate, with the same
    # source eligibility as live execution across legacy and V2 evidence.
    all_sources = [Permission(role="R4", org_scope="/", secret_level="secret", domain="*")]
    current_rows = await load_rule_sources(db, None, all_sources, statuses=["current"], effective=True)
    today = date.today()
    current_rows = [row for row in current_rows if (row[0].effective_from is None or row[0].effective_from <= today) and (row[0].effective_to is None or row[0].effective_to >= today)]
    verified_rows = await load_rule_sources(db, None, all_sources, statuses=["current"], effective=True, require_authority=True)
    verified_ids = {rule.rule_id for rule, _clause, _file in verified_rows if rule.reviewed_by and rule.reviewed_at}
    rule_current = len(current_rows)
    verified_rules = sum(rule.rule_id in verified_ids for rule, _clause, _file in current_rows)
    covered_regulations = len({(rule.source_kind, file.file_id) for rule, _clause, file in current_rows})
    rule_coverage = {
        "current_regulations": regulation_current,
        "current_clauses": clause_current,
        "covered_regulations": covered_regulations,
        "current_rules": rule_current,
        "verified_source_rules": verified_rules,
        "verified_source_rate": round(verified_rules / rule_current, 4) if rule_current else None,
        "featured_scenarios_passed": scenarios["pass_total"],
    }
    golden = golden_evidence()
    return {
        "trial": trial,
        "golden": golden,
        "scenario_validation": scenarios,
        "rule_coverage": rule_coverage,
        "award_readiness": build_award_readiness(trial, golden, rule_coverage),
        "engineering": {
            "backend_tests_passed": None,
            "backend_test_status": "not_attached_to_runtime_dashboard",
            "migration": migration_source_info(),
            "note": "测试通过数只来自本次发布门禁或导出执行记录，运行看板不以静态源码计数冒充。",
        },
    }
