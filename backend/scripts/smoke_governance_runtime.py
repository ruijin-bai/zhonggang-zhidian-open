"""Authenticated runtime smoke without printing or persisting credentials."""
from __future__ import annotations

import argparse
import asyncio
import json

import httpx
from sqlalchemy import select

from app.db.models.user import User
from app.db.session import SessionLocal
from app.services.auth.auth_service import issue_token


async def run(base_url: str, username: str) -> None:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
        if user is None or user.role != "R4":
            raise SystemExit(f"active R4 user not found: {username}")
        token = issue_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30) as client:
        tasks = (await client.get("/api/v1/governance/tasks")).raise_for_status().json()["data"]
        gaps = (await client.get("/api/v1/regulations/governance/gaps")).raise_for_status().json()["data"]
        coverage = (await client.get("/api/v1/rules/coverage")).raise_for_status().json()["data"]
        orgs = (await client.get("/api/v1/governance/org-units")).raise_for_status().json()["data"]
    print(json.dumps({
        "task_total": tasks["total"], "task_status_counts": tasks["status_counts"],
        "metadata_gap_total": gaps["total"], "rule_candidates": coverage["candidate_count"],
        "active_rules": coverage["active_rule_count"], "org_units": len(orgs),
    }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()
    asyncio.run(run(args.base_url, args.username))
