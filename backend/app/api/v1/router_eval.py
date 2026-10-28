"""Evaluation test-set & runner endpoints (T14)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import NotFoundError, ok
from app.db.session import get_db
from app.schemas.eval import EvalRunRequest, EvalRunResponse, TestCaseCreate, TestCaseOut
from app.services.eval.runner import EvalRunner
from app.services.eval.testset import create_case, delete_case, get_case, list_cases

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/testset", response_model=None)
async def list_cases_endpoint(
    scenario_tag: str | None = None,
    _: object = Depends(require_roles("R3", "R4")),
    db: AsyncSession = Depends(get_db),
):
    cases = await list_cases(db, scenario_tag)
    return ok(
        [
            TestCaseOut(
                case_id=c.case_id, question=c.question, expected_clause_ids=c.expected_clause_ids or [],
                standard_answer=c.standard_answer, scenario_tag=c.scenario_tag, status=c.status,
            ).model_dump()
            for c in cases
        ]
    )


@router.post("/testset", response_model=None)
async def create_case_endpoint(
    body: TestCaseCreate, _: object = Depends(require_roles("R3", "R4")), db: AsyncSession = Depends(get_db)
):
    case = await create_case(
        db, question=body.question, expected_clause_ids=body.expected_clause_ids,
        standard_answer=body.standard_answer, scenario_tag=body.scenario_tag, created_by=body.created_by,
    )
    await db.commit()
    return ok({"case_id": case.case_id})


@router.delete("/testset/{case_id}", response_model=None)
async def delete_case_endpoint(case_id: str, _: object = Depends(require_roles("R3", "R4")), db: AsyncSession = Depends(get_db)):
    case = await get_case(db, case_id)
    if case is None:
        raise NotFoundError("测试用例不存在")
    await delete_case(db, case)
    await db.commit()
    return ok({"case_id": case_id})


@router.post("/run", response_model=None)
async def run(body: EvalRunRequest, ctx=Depends(get_user_context), db: AsyncSession = Depends(get_db)):
    user, perms = ctx
    runner = EvalRunner()
    summary = await runner.run_testset(db, user=user, permissions=perms, case_ids=body.case_ids, reviewer=body.reviewer)
    await db.commit()
    return ok(EvalRunResponse(**summary).model_dump())
