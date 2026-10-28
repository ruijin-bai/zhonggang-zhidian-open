"""Run expert-reviewed business golden QA and export JSON + CSV."""
from __future__ import annotations

import argparse
import hashlib
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

from app.services.eval.business_golden import evaluate_case, summarize, validate_golden_cases

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden_business_qa.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8010")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default=os.getenv("EVAL_PASSWORD"))
    args = parser.parse_args()
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))
    errors = validate_golden_cases(cases)
    if errors:
        print("金标校验失败：\n" + "\n".join(errors))
        return 2
    if not cases:
        print("业务金标集为空：须由业务责任人审核后录入，不能用 smoke 题冒充。")
        return 3
    if not args.password:
        print("缺少 EVAL_PASSWORD 或 --password")
        return 2
    client = httpx.Client(base_url=args.base, timeout=180)
    login = client.post("/api/v1/auth/login", json={"username": args.username, "password": args.password})
    token = (login.json().get("data") or {}).get("access_token")
    if not token:
        print("登录失败")
        return 2
    headers = {"Authorization": f"Bearer {token}"}
    rows = []
    for case in cases:
        started = time.perf_counter()
        response = client.post(
            "/api/v1/qa/ask",
            json={"question": case["question"], "slots": case.get("facts", {}), "round": 2, "evaluation": True},
            headers=headers,
        )
        total_ms = round((time.perf_counter() - started) * 1000, 1)
        actual = (response.json().get("data") or {}) if response.status_code == 200 else {
            "need_human": True, "error_status": response.status_code,
        }
        actual["latency_total_ms"] = total_ms
        # Non-streaming endpoint cannot truthfully expose first-token latency.
        actual["latency_first_token_ms"] = None
        rows.append(evaluate_case(case, actual))
    result = summarize(rows)
    result["golden_dataset_sha256"] = hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    json_path = ROOT / "eval_golden_result.json"
    csv_path = ROOT / "eval_golden_result.csv"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({key: value for key, value in result.items() if key != "details"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
