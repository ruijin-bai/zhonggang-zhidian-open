"""Evaluation runner: replay test cases, compare recall/citation, persist results (T14)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import TestRunStatus
from app.db.models.eval import TestCase, TestRun
from app.services.qa_service import QAService


def _jaccard(expected: set[str], retrieved: set[str]) -> float:
    if not expected:
        return 0.0
    inter = len(expected & retrieved)
    return inter / len(expected)


class EvalRunner:
    def __init__(self) -> None:
        self.qa = QAService()

    @staticmethod
    def _answer_match(standard: str, answer: str) -> bool:
        if not standard.strip():
            return True
        normalize = lambda value: "".join(ch for ch in value.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
        expected = normalize(standard)
        actual = normalize(answer)
        if expected and expected in actual:
            return True
        expected_bigrams = {expected[i:i + 2] for i in range(max(0, len(expected) - 1))}
        if not expected_bigrams:
            return False
        actual_bigrams = {actual[i:i + 2] for i in range(max(0, len(actual) - 1))}
        return len(expected_bigrams & actual_bigrams) / len(expected_bigrams) >= 0.7

    async def run_case(
        self, session: AsyncSession, *, user, permissions, case: TestCase, reviewer: str | None = None
    ) -> TestRun:
        qa_result = await self.qa.ask(
            session,
            user=user,
            permissions=permissions,
            question=case.question,
            round_no=2,
            is_evaluation=True,
        )
        retrieved_ids = {c["clause_id"] for c in qa_result.get("citations", [])}
        expected = set(case.expected_clause_ids or [])
        recall_rate = _jaccard(expected, retrieved_ids)
        recall_match = expected.issubset(retrieved_ids) if expected else False
        source_consistent = bool(qa_result.get("citations")) and all(
            item.get("consistent") for item in qa_result["citations"]
        )
        grounding_match = bool(qa_result.get("grounding_passed"))
        citation_match = source_consistent and grounding_match
        answer_match = self._answer_match(case.standard_answer, qa_result.get("answer_interpret", ""))
        authority_match = bool(qa_result.get("authority_verified"))

        score = round(
            0.4 * recall_rate
            + 0.25 * float(citation_match)
            + 0.2 * float(answer_match)
            + 0.15 * float(authority_match),
            3,
        )

        run = TestRun(
            case_id=case.case_id,
            session_id=qa_result["session_id"],
            recall_match=recall_match,
            citation_match=citation_match,
            grounding_match=grounding_match,
            answer_match=answer_match,
            authority_match=authority_match,
            score=score,
            reviewer=reviewer,
            status=TestRunStatus.PENDING.value if reviewer is None else TestRunStatus.PASSED.value,
        )
        session.add(run)
        await session.flush()
        return run

    async def run_testset(
        self,
        session: AsyncSession,
        *,
        user,
        permissions,
        case_ids: list[str] | None,
        reviewer: str | None = None,
    ) -> dict:
        if case_ids:
            cases = []
            for cid in case_ids:
                c = await session.get(TestCase, cid)
                if c:
                    cases.append(c)
        else:
            cases = list((await session.execute(select(TestCase))).scalars().all())

        runs: list[TestRun] = []
        for case in cases:
            runs.append(await self.run_case(session, user=user, permissions=permissions, case=case, reviewer=reviewer))

        total = len(runs)
        recall_pass = sum(1 for r in runs if r.recall_match)
        citation_pass = sum(1 for r in runs if r.citation_match)
        grounding_pass = sum(1 for r in runs if r.grounding_match)
        answer_pass = sum(1 for r in runs if r.answer_match)
        authority_pass = sum(1 for r in runs if r.authority_match)
        avg = round(sum(r.score for r in runs) / total, 3) if total else 0.0
        return {
            "total": total,
            "recall_pass": recall_pass,
            "citation_pass": citation_pass,
            "grounding_pass": grounding_pass,
            "answer_pass": answer_pass,
            "authority_pass": authority_pass,
            "avg_score": avg,
            "recall_rate": round(recall_pass / total, 3) if total else 0.0,
            "runs": [
                {
                    "run_id": r.run_id,
                    "case_id": r.case_id,
                    "recall_match": r.recall_match,
                    "citation_match": r.citation_match,
                    "grounding_match": r.grounding_match,
                    "answer_match": r.answer_match,
                    "authority_match": r.authority_match,
                    "score": r.score,
                }
                for r in runs
            ],
        }
