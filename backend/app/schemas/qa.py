"""QA DTOs (architecture §3.2 ①)."""
from __future__ import annotations

from pydantic import BaseModel


class QAAskRequest(BaseModel):
    question: str
    session_id: str | None = None
    slots: dict = {}
    round: int = 1
    # Release regression traffic is isolated from real-user quality metrics.
    # The API accepts this flag only for R4 system administrators.
    evaluation: bool = False


class CitationOut(BaseModel):
    clause_id: str
    file_title: str
    regulation_code: str = ""
    clause_no: str
    excerpt: str
    consistent: bool
    source_page: int | None = None
    content_hash: str | None = None


class FollowUpPrompt(BaseModel):
    slot: str
    label: str
    options: list[str]


class FollowUpOut(BaseModel):
    round: int
    missing: list[str]
    prompts: list[FollowUpPrompt]


class QAAskResponse(BaseModel):
    session_id: str
    answer_interpret: str
    citations: list[CitationOut] = []
    confidence: float = 0.0
    degraded: bool = False
    # Machine-readable reason; present only when no trustworthy conclusion was produced.
    degraded_reason: str | None = None
    follow_up: FollowUpOut | None = None
    need_human: bool = False
    grounding_passed: bool = False
    grounding_coverage: float = 0.0
    authority_verified: bool = False
    quality_warnings: list[str] = []


class FeedbackRequest(BaseModel):
    session_id: str
    type: str  # favorite | like | correct
    content: str | None = None
