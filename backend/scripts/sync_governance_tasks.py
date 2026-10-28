"""Synchronize governance queues and optionally apply only high-confidence facts.

Usage from backend/: ``python -m scripts.sync_governance_tasks --apply-safe``.
Official codes and responsible departments are never inferred by this script.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date

from sqlalchemy import select

from app.db.models.governance_task import GovernanceTask
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.audit import record_audit
from app.services.auth.auth_service import get_user_permissions
from app.services.governance import sync_governance_tasks


async def run(username: str, apply_safe: bool) -> None:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None or user.role not in {"R3", "R4"}:
            raise SystemExit(f"R3/R4 user not found: {username}")
        perms = await get_user_permissions(db, user)
        first = await sync_governance_tasks(db, user, perms)
        applied: list[dict] = []
        if apply_safe:
            tasks = list((await db.execute(select(GovernanceTask).where(
                GovernanceTask.task_type == "regulation_metadata",
                GovernanceTask.status.in_(["open", "in_progress"]),
            ))).scalars().all())
            for task in tasks:
                regulation = await db.get(RegulationFile, task.file_id)
                if regulation is None:
                    continue
                suggestions = (task.evidence or {}).get("suggestions", {})
                changed: dict[str, dict] = {}
                domain = suggestions.get("domain")
                if regulation.domain == "*" and domain and domain.get("confidence") == "high":
                    regulation.domain = domain["value"]
                    changed["domain"] = domain
                effective = suggestions.get("effective_date")
                if regulation.effective_date is None and effective and effective.get("confidence") == "high":
                    regulation.effective_date = date.fromisoformat(effective["value"])
                    changed["effective_date"] = effective
                if changed:
                    await record_audit(
                        db, actor_id=user.user_id, action="regulation.metadata.evidence_applied",
                        target_type="regulation_file", target_id=regulation.file_id,
                        detail=json.dumps({"fields": changed, "method": "deterministic_rules_v1"}, ensure_ascii=False),
                    )
                    applied.append({"file_id": regulation.file_id, "title": regulation.title, "fields": sorted(changed)})
            await db.commit()
        final = await sync_governance_tasks(db, user, perms)
        print(json.dumps({"initial_sync": first, "safe_applied": applied, "final_sync": final, "applied_count": len(applied)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="admin")
    parser.add_argument("--apply-safe", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.username, args.apply_safe))
