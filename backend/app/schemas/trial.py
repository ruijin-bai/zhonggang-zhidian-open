"""Schemas for real-trial evidence collection."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


TrialEventType = Literal[
    "qa_started", "qa_completed", "citation_opened", "feedback_like",
    "feedback_correct", "case_created", "case_evaluated", "manual_review_requested",
]


class TrialEventCreate(BaseModel):
    event_type: TrialEventType
    session_id: str | None = Field(default=None, max_length=64)
    scenario: str | None = Field(default=None, max_length=64)
    result_state: str | None = Field(default=None, max_length=32)
    need_human: bool | None = None
    authority_verified: bool | None = None
    grounding_passed: bool | None = None
    latency_first_token_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    latency_total_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    is_trial: bool = False


class TrialBenchmarkCreate(BaseModel):
    scenario: str = Field(min_length=1, max_length=64)
    participant_id_hash: str = Field(min_length=16, max_length=64)
    manual_duration_seconds: float = Field(gt=0, le=86_400)
    ai_duration_seconds: float = Field(gt=0, le=86_400)
    manual_success: bool
    ai_success: bool
    manual_source_found: bool
    ai_source_found: bool
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("participant_id_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not all(ch in "0123456789abcdef" for ch in cleaned):
            raise ValueError("participant_id_hash 必须是不可逆十六进制哈希")
        return cleaned
