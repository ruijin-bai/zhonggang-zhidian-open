"""Export a self-describing competition evidence package from real records."""
from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from app.db.session import SessionLocal, dispose_engine
from app.services.competition.evidence import build_competition_evidence

ROOT = Path(__file__).resolve().parents[2]
MODEL_REPORT_PATH = ROOT / "backend" / "model_runtime_verification.json"


def _git_sha() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _safe_model_runtime_summary(path: Path = MODEL_REPORT_PATH) -> dict:
    """Whitelist runtime evidence fields; discard prompts, bodies and unknown keys."""
    if not path.exists():
        return {"available": False}
    raw = json.loads(path.read_text(encoding="utf-8"))
    safe: dict = {
        "available": True,
        "all_passed": bool(raw.get("all_passed")),
        "component_checks_passed": bool(raw.get("component_checks_passed")),
        "qa_chain_passed": bool(raw.get("qa_chain_passed")),
        "component_runs": int(raw.get("component_runs") or 0),
        "checks": {},
        "security": "whitelisted_fields_only_no_prompts_or_provider_bodies",
    }
    check_keys = {
        "status", "provider_kind", "expected_dim", "observed_dims",
        "observed_dim_counts", "reason", "error_code",
    }
    run_keys = {
        "run", "status", "latency_ms", "vector_dim", "degraded",
        "need_human", "error_code",
    }
    for name, item in (raw.get("checks") or {}).items():
        if not isinstance(item, dict):
            continue
        clean = {key: item[key] for key in check_keys if key in item}
        if isinstance(item.get("runs"), list):
            clean["runs"] = [
                {key: run[key] for key in run_keys if key in run}
                for run in item["runs"] if isinstance(run, dict)
            ]
        safe["checks"][str(name)[:32]] = clean
    return safe


async def _export(output: Path, verified_test_count: int | None) -> None:
    async with SessionLocal() as session:
        evidence = await build_competition_evidence(session)
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trial": evidence["trial"],
        "golden": evidence["golden"],
        "rule_coverage": evidence["rule_coverage"],
        "award_readiness": evidence["award_readiness"],
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(output / "summary.csv", [
        {"metric": key, "value": value if value is not None else "", "scope": "real_trial"}
        for key, value in evidence["trial"].items() if not isinstance(value, (dict, list))
    ])
    (output / "qa_metrics.json").write_text(json.dumps(evidence["golden"], ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(output / "trial_metrics.csv", [
        {"metric": key, "value": value if value is not None else ""}
        for key, value in evidence["trial"].items() if not isinstance(value, (dict, list))
    ])
    (output / "scenario_validation.json").write_text(json.dumps(evidence["scenario_validation"], ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "award_readiness.json").write_text(json.dumps(evidence["award_readiness"], ensure_ascii=False, indent=2), encoding="utf-8")
    model_runtime = _safe_model_runtime_summary()
    (output / "model_runtime_summary.json").write_text(
        json.dumps(model_runtime, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    system_info = {
        "git_commit_sha": _git_sha(),
        "generated_at": summary["generated_at"],
        "backend_tests_passed": verified_test_count,
        "backend_test_status": "verified_in_current_run" if verified_test_count is not None else "not_supplied",
        "migration_head": evidence["engineering"]["migration"]["heads"],
        "migration_single_root_single_head": evidence["engineering"]["migration"]["single_root_single_head"],
        "regulation_count": evidence["rule_coverage"]["current_regulations"],
        "clause_count": evidence["rule_coverage"]["current_clauses"],
        "rule_count": evidence["rule_coverage"]["current_rules"],
        "golden_test_count": evidence["golden"]["expert_reviewed_total"],
        "real_model_verification_available": model_runtime["available"],
        "real_model_all_passed": model_runtime.get("all_passed"),
        "real_model_configuration": "credentials_omitted_check_model_runtime_summary",
    }
    (output / "system_info.json").write_text(json.dumps(system_info, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "README.md").write_text(
        "# 中港智典竞赛证据包\n\n"
        "本目录由真实数据库与当前Git版本生成。空值表示未提供真实证据，不以demo或mock填充。\n\n"
        "- `qa_metrics.json` 仅接受业务专家签审golden结果；smoke recall不等于业务答案准确率。\n"
        "- `trial_metrics.csv` 仅统计显式标记的真实试用事件。\n"
        "- `scenario_validation.json` 按制度、规则、事项和版本证据逐项闭锁。\n"
        "- `award_readiness.json` 对照最低样本门槛列出当前值、目标值、责任人和下一步。\n"
        "- `model_runtime_summary.json` 仅含白名单状态与耗时，不含问题、条款正文、密钥、URL或供应商响应。\n"
        "- `system_info.json` 不输出任何API Key。\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "backend" / "competition_evidence"))
    parser.add_argument("--verified-test-count", type=int, default=None, help="仅填写本次已实际通过的pytest数量")
    args = parser.parse_args()
    async def export_and_cleanup() -> None:
        try:
            await _export(Path(args.output).resolve(), args.verified_test_count)
        finally:
            await dispose_engine()

    asyncio.run(export_and_cleanup())
    print(f"EVIDENCE_EXPORTED {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
