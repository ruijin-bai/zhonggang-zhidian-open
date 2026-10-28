"""Citation (溯源) construction and consistency verification (architecture §6 T08)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from app.services.rag.retriever import RetrievedClause


@dataclass
class Citation:
    clause_id: str
    file_title: str
    regulation_code: str
    clause_no: str
    excerpt: str
    consistent: bool
    source_page: int | None = None
    content_hash: str | None = None


def _truncate(text: str, limit: int = 400) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CitationService:
    """Build source cards and verify each excerpt against its source clause."""

    @staticmethod
    def check_consistency(excerpt: str, source_content: str) -> bool:
        """An excerpt is consistent when it is a substring of the source clause.

        截断产生的尾部省略号（…）不属于原文，比对前先剥离，避免长条款的
        合法摘录被误判为不一致（评估「引用率」因此恒为 0）。
        """
        if not excerpt or not source_content:
            return False
        probe = excerpt.strip().rstrip("…").rstrip()
        return probe in source_content

    def build_citations(self, candidates: list[RetrievedClause], limit: int = 400) -> list[Citation]:
        out: list[Citation] = []
        for c in candidates:
            excerpt = _truncate(c.clause.content, limit)
            consistent = self.check_consistency(excerpt, c.clause.content)
            out.append(
                Citation(
                    clause_id=c.clause.clause_id,
                    file_title=c.file.title,
                    regulation_code=c.file.regulation_code,
                    clause_no=c.clause.clause_no,
                    excerpt=excerpt,
                    consistent=consistent,
                    source_page=c.clause.source_page,
                    content_hash=c.clause.content_hash or hashlib.sha256(c.clause.content.encode("utf-8")).hexdigest(),
                )
            )
        return out

    def verify(self, citations: list[Citation], clause_map: dict[str, str]) -> tuple[bool, list[Citation]]:
        """Re-check citations against a {clause_id: content} map; mark inconsistent."""
        ok = True
        for cit in citations:
            src = clause_map.get(cit.clause_id, "")
            cit.consistent = self.check_consistency(cit.excerpt, src)
            if not cit.consistent:
                ok = False
        return ok, citations
