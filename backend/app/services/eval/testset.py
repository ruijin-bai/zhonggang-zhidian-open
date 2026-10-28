"""Evaluation test-set CRUD helpers (architecture §6 T14)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import gen_id
from app.db.models.eval import TestCase


async def create_case(
    session: AsyncSession,
    *,
    question: str,
    expected_clause_ids: list[str],
    standard_answer: str,
    scenario_tag: str | None,
    created_by: str | None,
) -> TestCase:
    case = TestCase(
        case_id=gen_id("case"),
        question=question,
        expected_clause_ids=expected_clause_ids,
        standard_answer=standard_answer,
        scenario_tag=scenario_tag,
        created_by=created_by,
        status="active",
    )
    session.add(case)
    await session.flush()
    return case


async def list_cases(session: AsyncSession, scenario_tag: str | None = None) -> list[TestCase]:
    stmt = select(TestCase)
    if scenario_tag:
        stmt = stmt.where(TestCase.scenario_tag == scenario_tag)
    stmt = stmt.order_by(TestCase.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_case(session: AsyncSession, case_id: str) -> TestCase | None:
    return await session.get(TestCase, case_id)


async def delete_case(session: AsyncSession, case: TestCase) -> None:
    await session.delete(case)
    await session.flush()
