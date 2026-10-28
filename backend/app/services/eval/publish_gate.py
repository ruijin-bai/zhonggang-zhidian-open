"""Evidence-based readiness gate for publishing a newly ingested regulation."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ClauseStatus, SecretLevel, TestStatus
from app.db.models.clause import Clause
from app.db.models.eval import TestCase
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User
from app.services.rag.citation import CitationService
from app.services.rag.retriever import RetrieverService


def _candidate_queries(clauses: list[Clause], cases: list[TestCase], title: str = "") -> list[str]:
    clause_ids = {clause.clause_id for clause in clauses}
    tags = {tag for clause in clauses for tag in (clause.scenario_tags or [])}
    queries = [
        case.question.strip()
        for case in cases
        if case.question.strip()
        and (
            clause_ids.intersection(case.expected_clause_ids or [])
            or (case.scenario_tag and case.scenario_tag in tags)
        )
    ]
    # There is normally no existing test case for a just-created clause ID.  In
    # that case, select information-rich units across the document instead of
    # blindly sampling the first three title-page rows. Include the authoritative
    # document title to test the same title+content retrieval path users rely on.
    if not queries:
        informative = [
            clause for clause in clauses
            if len(clause.content.strip()) >= 12
            and not re.fullmatch(r"第?\s*\d+\s*页?", clause.content.strip())
        ] or clauses
        ranked = sorted(
            informative,
            key=lambda clause: (
                len(set(re.sub(r"\s+", "", clause.content[:300]))),
                len(clause.content),
            ),
            reverse=True,
        )
        queries = [
            f"{title} {clause.clause_no} {clause.content[:180]}".strip()
            for clause in ranked[:3]
        ]
    return list(dict.fromkeys(query for query in queries if query))[:3]


async def evaluate_publish_candidate(
    session: AsyncSession,
    regulation: RegulationFile,
) -> dict:
    """Verify that a candidate version is retrievable and citable before release.

    The candidate is made visible only within the uncommitted ingestion
    transaction.  It never becomes externally retrievable until this gate and
    the subsequent publication transaction both succeed.
    """
    clauses = list(
        (
            await session.execute(
                select(Clause).where(
                    Clause.file_id == regulation.file_id,
                    Clause.status == ClauseStatus.CURRENT.value,
                )
            )
        ).scalars()
    )
    if regulation.parse_quality_score is not None and regulation.parse_quality_score < 72:
        return {
            "passed": False,
            "reason": f"发布评估未通过：解析质量分 {regulation.parse_quality_score}，低于 72",
            "checks": [],
        }
    if not clauses or not any(clause.content.strip() for clause in clauses):
        return {"passed": False, "reason": "发布评估未通过：未解析出可检索的制度条款", "checks": []}
    if any(clause.embedding is None for clause in clauses):
        return {"passed": False, "reason": "发布评估未通过：制度条款尚未完成向量化", "checks": []}

    cases = list(
        (
            await session.execute(select(TestCase).where(TestCase.status == TestStatus.ACTIVE.value))
        ).scalars()
    )
    queries = _candidate_queries(clauses, cases, regulation.title)
    if not queries:
        return {"passed": False, "reason": "发布评估未通过：无法生成检索校验项", "checks": []}

    # Use a non-persisted, maximum-clearance evaluator.  This evaluates index
    # readiness only; external caller permissions remain enforced by normal RAG.
    evaluator = User(user_id="system_publish_gate", role="R4", secret_clearance=SecretLevel.SECRET.value)
    permission = Permission(role="R4", org_scope="/", secret_level=SecretLevel.SECRET.value, domain="*")
    retriever = RetrieverService()
    citation_service = CitationService()
    previous_status = regulation.status
    regulation.status = "current"
    await session.flush()
    checks: list[dict] = []
    try:
        for query in queries:
            results = await retriever.retrieve(
                # Publication checks use a wider audit pool than normal QA.
                # Large handbooks often share generic headings, so a top-10
                # cut can reject an otherwise exact, citable candidate.
                session, evaluator, [permission], query, top_k=200, min_score=0.0
            )
            candidate_results = [item for item in results if item.file.file_id == regulation.file_id]
            citations = citation_service.build_citations(candidate_results)
            consistent, citations = citation_service.verify(
                citations,
                {item.clause.clause_id: item.clause.content for item in candidate_results},
            )
            passed = bool(candidate_results) and consistent and all(citation.consistent for citation in citations)
            checks.append(
                {
                    "query": query,
                    "candidate_hit": bool(candidate_results),
                    "citation_consistent": bool(consistent),
                    "candidate_count": len(candidate_results),
                    "inconsistent_clause_ids": [
                        citation.clause_id for citation in citations if not citation.consistent
                    ][:5],
                    "passed": passed,
                }
            )
    finally:
        regulation.status = previous_status
        await session.flush()

    if not all(check["passed"] for check in checks):
        return {
            "passed": False,
            "reason": "发布评估未通过：新版本未通过检索或引用一致性校验",
            "checks": checks,
        }
    return {"passed": True, "reason": "", "checks": checks}
