"""Evaluation runner test: recall/citation comparison (T14)."""
from __future__ import annotations

from app.adapters.embedding.factory import get_embedding_adapter
from app.db.models.clause import Clause
from app.db.models.eval import TestCase
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.eval.runner import EvalRunner


async def test_eval_runner_recall_match(session):
    file = RegulationFile(
        title="境外项目管理办法", owner_org=None, org_path="/",
        secret_level="internal", domain="境外项目", status="current",
    )
    session.add(file)
    await session.flush()
    content = "境外项目变更款审批：单笔变更款超过50万美元的，须报区域总经理审核后报总部审批。"
    emb = get_embedding_adapter().embed([content])[0]
    clause = Clause(
        file_id=file.file_id, clause_no="第12条", content=content,
        secret_level="internal", scenario_tags=["变更款审批"], embedding=emb, status="current",
    )
    session.add(clause)
    await session.flush()

    case = TestCase(
        case_id="case_x", question="境外项目变更款50万美元由谁审批？",
        expected_clause_ids=[clause.clause_id], standard_answer="须报总部审批。",
        scenario_tag="变更款审批", status="active",
    )
    session.add(case)
    await session.flush()

    user = User(user_id="u1", role="R4", secret_clearance="secret")
    perm = Permission(role="R4", org_scope="/", secret_level="secret", domain="*")
    runner = EvalRunner()
    run = await runner.run_case(session, user=user, permissions=[perm], case=case, reviewer="user_r2")
    assert run.recall_match is True
    assert run.citation_match is True
    assert run.score > 0.5
