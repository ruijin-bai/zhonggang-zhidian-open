"""Synthetic organisation-boundary contracts for legacy and V2 retrieval."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.asset import KnowledgeAsset
from app.db.models.clause import Clause
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.permission.rbac import build_asset_filter, build_filter


PATHS = {
    "company": "/",
    "hq": "/hq",
    "hq_tail": "/hq/",
    "a": "/hq/a",
    "a_tail": "/hq/a/",
    "ab": "/hq/ab",
    "ab_tail": "/hq/ab/",
    "ab_child": "/hq/ab/child",
    "other_root": "/region",
    "root_prefix": "/hqx",
    "percent": "/hq/a%",
    "percent_lookalike": "/hq/axy",
    "underscore": "/hq/a_",
}


@pytest.mark.parametrize(("scope", "expected"), [
    ("/hq/ab", {"company", "hq", "hq_tail", "ab", "ab_tail"}),
    ("/hq/ab/", {"company", "hq", "hq_tail", "ab", "ab_tail"}),
    ("/hq/ab/child", {"company", "hq", "hq_tail", "ab", "ab_tail", "ab_child"}),
    ("/hq/a", {"company", "hq", "hq_tail", "a", "a_tail"}),
    ("/hq", {"company", "hq", "hq_tail"}),
    ("/hq/a%", {"company", "hq", "hq_tail", "percent"}),
    ("/hq/a_", {"company", "hq", "hq_tail", "underscore"}),
    ("/", set(PATHS)),
    ("", set()),
    ("hq/ab", set()),
    ("/hq//ab", set()),
])
async def test_legacy_and_v2_org_gates_select_exact_ancestor_rows(session, scope, expected):
    """Actual SQL execution must not admit siblings, descendants or wildcards."""
    for key, path in PATHS.items():
        session.add(RegulationFile(
            file_id=f"legacy_{key}", title=f"Synthetic {key}", org_path=path,
            secret_level="internal", domain="synthetic", status="current",
        ))
        session.add(KnowledgeAsset(
            asset_id=f"asset_{key}", asset_type="management_method", title=f"Synthetic {key}",
            org_path=path, secret_level="internal", domain="synthetic", status="active",
        ))
    await session.flush()
    user = User(user_id="synthetic_org_reader", role="R1", secret_clearance="internal")
    permission = Permission(role="R1", org_scope=scope, secret_level="internal", domain="synthetic")
    legacy = set((await session.execute(
        select(RegulationFile.file_id).where(build_filter(user, [permission]))
    )).scalars())
    compound = set((await session.execute(
        select(KnowledgeAsset.asset_id).where(build_asset_filter(
            user, [permission], secret_level=KnowledgeAsset.secret_level,
            org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain,
        ))
    )).scalars())
    assert legacy == {f"legacy_{key}" for key in expected}
    assert compound == {f"asset_{key}" for key in expected}


async def test_retriever_excludes_sibling_prefix_and_child_sources_from_both_backends(session):
    from test_compound_retrieval import _seed_compound_unit
    from app.adapters.embedding.factory import get_embedding_adapter
    from app.services.rag.retriever import (
        RetrieverService, reset_compound_vector_cache, reset_memory_vector_cache,
    )

    expected = set()
    text = "境外项目单笔变更超过五十万美元的，应报总部审批。"
    for index, path in enumerate(("/", "/hq", "/hq/a", "/hq/ab", "/hq/ab/child")):
        file = RegulationFile(
            file_id=f"org_retrieval_{index}", title="Synthetic 境外项目审批办法",
            org_path=path, secret_level="internal", domain="境外项目", status="current",
        )
        session.add(file)
        await session.flush()
        legacy_text = f"Synthetic legacy fixture {index}: {text}"
        clause = Clause(
            clause_id=f"org_clause_{index}", file_id=file.file_id, clause_no="第十二条",
            # The normal legacy retrieval path requires an indexed embedding.
            content=legacy_text, embedding=get_embedding_adapter().embed([legacy_text])[0],
            status="current", secret_level="internal",
        )
        session.add(clause)
        unit, asset = await _seed_compound_unit(session)
        asset.org_path = path
        if path in {"/", "/hq", "/hq/ab"}:
            expected.update((clause.clause_id, unit.unit_id))
    await session.flush()
    reset_memory_vector_cache()
    reset_compound_vector_cache()
    user = User(user_id="synthetic_retrieval_reader", role="R1", secret_clearance="internal")
    permission = Permission(role="R1", org_scope="/hq/ab/", secret_level="internal", domain="*")
    results = await RetrieverService().retrieve(session, user, [permission], text, top_k=20, min_score=0)
    assert {result.clause.clause_id for result in results} == expected
