"""Validate configured featured scenarios against current database evidence."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.db.session import SessionLocal
from app.services.competition.scenarios import validate_competition_scenarios


async def _run() -> int:
    async with SessionLocal() as session:
        result = await validate_competition_scenarios(session)
    output = Path(__file__).resolve().parent.parent / "competition_scenario_validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "scenarios"}, ensure_ascii=False, indent=2))
    for item in result["scenarios"]:
        print(f"{item['status']:4} {item['scenario']}: {', '.join(item['gaps']) or 'all checks passed'}")
    print(f"报告：{output}")
    return 0 if result["all_passed"] else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
