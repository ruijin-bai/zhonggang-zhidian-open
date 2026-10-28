"""Retriever (memory/sqlite path) end-to-end test with mock embeddings (T07)."""
from __future__ import annotations

from app.adapters.embedding.factory import get_embedding_adapter
from app.core.exceptions import EmbeddingError
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.qa import QASession
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.rag.retriever import (
    RetrieverService,
    reset_memory_vector_cache,
    warm_memory_vector_cache,
)
import app.services.rag.retriever as retriever_module


async def test_retriever_finds_relevant_clause(session):
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

    user = User(user_id="u1", role="R4", secret_clearance="secret")
    perm = Permission(role="R4", org_scope="/", secret_level="secret", domain="*")
    svc = RetrieverService()
    results = await svc.retrieve(
        session, user, [perm], "境外项目变更款50万美元由谁审批？", top_k=3, min_score=0.1
    )
    assert results, "应当检索到相关条款"
    assert results[0].clause.clause_id == clause.clause_id


async def test_retriever_respects_permission(session):
    file = RegulationFile(
        title="内部审计规定", owner_org=None, org_path="/hq",
        secret_level="confidential", domain="*", status="current",
    )
    session.add(file)
    await session.flush()
    emb = get_embedding_adapter().embed(["内部审计有权调阅全部财务资料"])[0]
    clause = Clause(
        file_id=file.file_id, clause_no="第4条", content="内部审计有权调阅全部财务资料。",
        secret_level="confidential", scenario_tags=[], embedding=emb, status="current",
    )
    session.add(clause)
    await session.flush()

    # R1 employee limited to internal + overseas subtree → must NOT see confidential.
    user = User(user_id="u2", role="R1", secret_clearance="internal")
    perm = Permission(role="R1", org_scope="/hq/region1/overseas1", secret_level="internal", domain="*")
    svc = RetrieverService()
    results = await svc.retrieve(
        session, user, [perm], "内部审计调阅哪些资料", top_k=5, min_score=0.0
    )
    assert all(r.clause.secret_level == "internal" for r in results)


async def test_retriever_excludes_clause_above_role_permission_ceiling(session):
    file = RegulationFile(
        title="项目制度", owner_org=None, org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    session.add(file)
    await session.flush()
    internal_content = "项目审批流程应按内部制度执行。"
    confidential_content = "项目审批流程的机密补充要求。"
    vectors = get_embedding_adapter().embed([internal_content, confidential_content])
    session.add_all([
        Clause(
            file_id=file.file_id, clause_no="第一条", content=internal_content,
            secret_level="internal", scenario_tags=[], embedding=vectors[0], status="current",
        ),
        Clause(
            file_id=file.file_id, clause_no="第二条", content=confidential_content,
            secret_level="confidential", scenario_tags=[], embedding=vectors[1], status="current",
        ),
    ])
    await session.flush()

    # The account itself is secret-cleared, but the R1 permission only allows internal data.
    user = User(user_id="u_secret_user", role="R1", secret_clearance="secret")
    perm = Permission(role="R1", org_scope="/", secret_level="internal", domain="*")
    results = await RetrieverService().retrieve(
        session, user, [perm], "项目审批流程", top_k=5, min_score=0.0
    )
    assert results
    assert all(item.clause.secret_level == "internal" for item in results)


async def test_retriever_falls_back_to_permission_filtered_lexical_search(session, monkeypatch):
    file = RegulationFile(
        title="员工借调管理办法", owner_org=None, org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    session.add(file)
    await session.flush()
    clause = Clause(
        file_id=file.file_id, clause_no="第八条", content="员工借调应提交申请并经所在单位批准。",
        secret_level="internal", scenario_tags=["员工借调"], embedding=None, status="current",
    )
    session.add(clause)
    await session.flush()

    user = User(user_id="u_fallback", role="R4", secret_clearance="secret")
    perm = Permission(role="R4", org_scope="/", secret_level="secret", domain="*")
    svc = RetrieverService()

    def unavailable(_texts):
        raise EmbeddingError("provider offline")

    monkeypatch.setattr(svc.embed, "embed", unavailable)
    results = await svc.retrieve(session, user, [perm], "员工借调怎么办理", top_k=3, min_score=0.1)
    assert results
    assert results[0].clause.clause_id == clause.clause_id


def test_lexical_ranking_uses_regulation_title_as_business_signal():
    target_file = RegulationFile(
        file_id="file_leave", title="中国港湾员工考勤休假管理办法",
        status="current", secret_level="internal",
    )
    other_file = RegulationFile(
        file_id="file_other", title="员工调配管理办法",
        status="current", secret_level="internal",
    )
    target = Clause(
        clause_id="clause_leave", file_id=target_file.file_id, clause_no="第一条",
        content="本办法适用于公司员工。", status="current", secret_level="internal",
    )
    distractor = Clause(
        clause_id="clause_other", file_id=other_file.file_id, clause_no="第二条",
        content="员工应按照工作安排申请年休假。", status="current", secret_level="internal",
    )
    ranked = RetrieverService()._rank_candidates(
        [(distractor, other_file), (target, target_file)], [], "员工考勤休假规定",
        top_k=2, min_score=0.0,
    )
    assert ranked[0].clause.clause_id == target.clause_id


async def test_memory_hybrid_unions_title_match_outside_vector_prefilter(session, monkeypatch):
    target_file = RegulationFile(
        file_id="file_attendance", title="中国港湾员工考勤休假管理办法",
        owner_org=None, org_path="/", secret_level="internal", domain="*", status="current",
    )
    distractor_file = RegulationFile(
        file_id="file_vector", title="一般管理办法", owner_org=None, org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    session.add_all([target_file, distractor_file])
    await session.flush()
    target = Clause(
        file_id=target_file.file_id, clause_no="第一条", content="本办法适用于公司员工。",
        secret_level="internal", embedding=[0.0, 1.0], status="current",
    )
    distractor = Clause(
        file_id=distractor_file.file_id, clause_no="第一条", content="通用管理要求。",
        secret_level="internal", embedding=[1.0, 0.0], status="current",
    )
    session.add_all([target, distractor])
    await session.flush()
    user = User(user_id="u_title_union", role="R4", secret_clearance="secret")
    perm = Permission(role="R4", org_scope="/", secret_level="secret", domain="*")
    svc = RetrieverService()
    monkeypatch.setattr(svc.embed, "embed", lambda _texts: [[1.0, 0.0]])
    monkeypatch.setattr(retriever_module._SETTINGS, "RETRIEVE_PREFILTER", 1)

    results = await svc.retrieve(
        session, user, [perm], "加班调休有哪些要求", top_k=1, min_score=0.0
    )
    assert results[0].clause.clause_id == target.clause_id


async def test_qa_write_does_not_invalidate_vector_source_cache(session):
    file = RegulationFile(
        title="缓存失效测试制度", owner_org=None, org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    user = User(
        user_id="u_cache_state",
        username="cache_state_user",
        hashed_password="test-only",
        role="R4",
        secret_clearance="secret",
    )
    session.add_all([file, user])
    await session.flush()
    vector = get_embedding_adapter().embed(["缓存只应随制度条款变化"])[0]
    session.add(Clause(
        file_id=file.file_id, clause_no="第一条", content="缓存只应随制度条款变化。",
        secret_level="internal", embedding=vector, status="current",
    ))
    await session.flush()

    reset_memory_vector_cache()
    before = await warm_memory_vector_cache(session, len(vector))
    session.add(QASession(
        user_id=user.user_id,
        question="无关QA写入",
        answer_interpret="仅用于缓存失效回归",
        is_evaluation=True,
    ))
    await session.commit()
    after = await warm_memory_vector_cache(session, len(vector))

    assert after is before
