"""Validate human-provided competition evidence without importing or exposing row data."""
from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "docs" / "delivery" / "业务协同补证包"
DEFAULT_OUTPUT = ROOT / "backend" / "business_handoff_validation.json"

FILE_SPECS = {
    "authority_metadata": (
        "01_制度权威元数据.csv",
        {"scenario", "regulation_title", "regulation_code", "effective_date", "owner_org", "domain", "reviewer_code", "reviewed_at", "original_confirmed"},
    ),
    "featured_rules": (
        "02_精品场景规则.csv",
        {"scenario", "regulation_code", "clause_no", "org_scope", "approver_path", "required_materials", "reviewer_code", "reviewed_at"},
    ),
    "golden_cases": (
        "03_业务专家金标.csv",
        {"id", "category", "scenario", "question", "facts_json", "expected_sources_json", "expected_claims_json", "expected_numbers_json", "expected_need_human", "expected_answer_mode", "reviewer", "reviewed_at"},
    ),
    "trial_roster": (
        "04_真实试用匿名名单.csv",
        {"participant_code", "role_group", "org_level", "scenario_group", "trial_start_date", "consent_confirmed"},
    ),
    "benchmarks": (
        "05_人工AI对照计时.csv",
        {"scenario", "participant_code", "manual_duration_seconds", "ai_duration_seconds", "manual_success", "ai_success", "manual_source_found", "ai_source_found"},
    ),
    "department_signoff": (
        "06_业务部门验证意见.csv",
        {"department", "signer_role", "signed_at", "trial_start_date", "trial_end_date", "conclusion", "attachment_path"},
    ),
}

MONETARY_SCENARIOS = {"contract_change", "procurement", "payment"}
TRUE_VALUES = {"true", "1", "yes", "y", "是"}
FALSE_VALUES = {"false", "0", "no", "n", "否"}
ANSWER_MODES = {"authoritative", "clarify", "refuse", "manual_review"}


def _rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = [
            {key: (value or "").strip() for key, value in row.items() if key is not None}
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]
    return headers, rows


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _valid_bool(value: str) -> bool:
    return value.strip().lower() in TRUE_VALUES | FALSE_VALUES


def _validate_rows(name: str, rows: list[dict[str, str]], errors: list[str]) -> None:
    date_fields = {
        "authority_metadata": {"effective_date", "reviewed_at"},
        "featured_rules": {"reviewed_at"},
        "golden_cases": {"reviewed_at"},
        "trial_roster": {"trial_start_date"},
        "department_signoff": {"signed_at", "trial_start_date", "trial_end_date"},
    }.get(name, set())
    bool_fields = {
        "authority_metadata": {"original_confirmed"},
        "golden_cases": {"expected_need_human"},
        "trial_roster": {"consent_confirmed"},
        "benchmarks": {"manual_success", "ai_success", "manual_source_found", "ai_source_found"},
    }.get(name, set())
    for index, row in enumerate(rows, start=2):
        for field in date_fields:
            if row.get(field) and not _valid_date(row[field]):
                errors.append(f"{name} row {index}: {field} 必须为YYYY-MM-DD")
        for field in bool_fields:
            if row.get(field) and not _valid_bool(row[field]):
                errors.append(f"{name} row {index}: {field} 必须填写是/否或true/false")

        if name == "featured_rules":
            scenario = row.get("scenario", "")
            if scenario in MONETARY_SCENARIOS:
                if not row.get("currency") or not (row.get("amount_min_minor") or row.get("amount_max_minor")):
                    errors.append(f"{name} row {index}: 金额场景必须填写币种和至少一个金额边界")
            for field in ("approver_path", "required_materials"):
                values = [item.strip() for item in row.get(field, "").split("|") if item.strip()]
                if not values:
                    errors.append(f"{name} row {index}: {field} 至少填写一项，使用|分隔")

        if name == "golden_cases":
            if row.get("expected_answer_mode") not in ANSWER_MODES:
                errors.append(f"{name} row {index}: expected_answer_mode 无效")
            json_fields = {
                "facts_json": dict,
                "expected_sources_json": list,
                "expected_claims_json": list,
                "expected_numbers_json": list,
            }
            for field, expected_type in json_fields.items():
                try:
                    value = json.loads(row.get(field, ""))
                    if not isinstance(value, expected_type):
                        raise TypeError
                except (json.JSONDecodeError, TypeError):
                    errors.append(f"{name} row {index}: {field} 不是有效{expected_type.__name__} JSON")

        if name == "benchmarks":
            for field in ("manual_duration_seconds", "ai_duration_seconds"):
                try:
                    if float(row.get(field, "0")) <= 0:
                        raise ValueError
                except ValueError:
                    errors.append(f"{name} row {index}: {field} 必须大于0")


def validate_handoff(input_dir: Path) -> dict:
    errors: list[str] = []
    datasets: dict[str, dict] = {}
    loaded: dict[str, list[dict[str, str]]] = {}
    for name, (filename, required_headers) in FILE_SPECS.items():
        path = input_dir / filename
        if not path.exists():
            errors.append(f"缺少文件：{filename}")
            datasets[name] = {"file": filename, "rows": 0, "headers_valid": False}
            loaded[name] = []
            continue
        headers, rows = _rows(path)
        missing = sorted(required_headers - set(headers))
        if missing:
            errors.append(f"{filename} 缺少列：{', '.join(missing)}")
        for index, row in enumerate(rows, start=2):
            blank = sorted(field for field in required_headers if not row.get(field))
            if blank:
                errors.append(f"{name} row {index}: 必填项为空 {', '.join(blank)}")
        _validate_rows(name, rows, errors)
        datasets[name] = {"file": filename, "rows": len(rows), "headers_valid": not missing}
        loaded[name] = rows

    participant_codes = [row.get("participant_code") for row in loaded["trial_roster"]]
    if len(participant_codes) != len(set(participant_codes)):
        errors.append("trial_roster: participant_code 必须唯一")
    roster_codes = set(participant_codes)
    unknown_codes = sorted({row.get("participant_code") for row in loaded["benchmarks"]} - roster_codes)
    if unknown_codes:
        errors.append(f"benchmarks: 存在未登记的participant_code，共{len(unknown_codes)}个")

    scenario_sets = []
    for name in ("authority_metadata", "featured_rules", "golden_cases"):
        scenario_sets.append({row.get("scenario") for row in loaded[name] if row.get("scenario")})
    governed_scenarios = set.intersection(*scenario_sets) if scenario_sets else set()
    gates = [
        {"key": "trial_participants", "current": len(roster_codes), "target": 20},
        {"key": "benchmark_records", "current": len(loaded["benchmarks"]), "target": 30},
        {"key": "golden_cases", "current": len(loaded["golden_cases"]), "target": 30},
        {"key": "governed_scenarios", "current": len(governed_scenarios), "target": 3},
        {"key": "department_signoff", "current": len(loaded["department_signoff"]), "target": 1},
    ]
    for gate in gates:
        gate["passed"] = gate["current"] >= gate["target"]
    return {
        "ready_for_import_review": not errors and all(gate["passed"] for gate in gates),
        "datasets": datasets,
        "gates": gates,
        "error_count": len(errors),
        "errors": errors,
        "disclaimer": "本报告只检查协同材料的结构与最低数量，不导入数据库、不输出原始行，也不替代业务责任人签审和系统场景PASS。",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    result = validate_handoff(Path(args.input).resolve())
    output = Path(args.output).resolve()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "errors"}, ensure_ascii=False, indent=2))
    if result["errors"]:
        print("\n需修正：")
        for error in result["errors"][:30]:
            print(f"- {error}")
    print(f"报告：{output}")
    return 0 if result["ready_for_import_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
