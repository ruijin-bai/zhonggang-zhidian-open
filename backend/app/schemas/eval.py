"""Evaluation DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class TestCaseCreate(BaseModel):
    question: str
    expected_clause_ids: list[str] = []
    standard_answer: str = ""
    scenario_tag: str | None = None
    created_by: str | None = None


class TestCaseOut(BaseModel):
    case_id: str
    question: str
    expected_clause_ids: list[str] = []
    standard_answer: str
    scenario_tag: str | None = None
    status: str


class EvalRunRequest(BaseModel):
    case_ids: list[str] | None = None
    reviewer: str | None = None


class EvalRunResponse(BaseModel):
    total: int
    recall_pass: int
    citation_pass: int
    grounding_pass: int = 0
    answer_pass: int = 0
    authority_pass: int = 0
    avg_score: float
    recall_rate: float
    runs: list = []
