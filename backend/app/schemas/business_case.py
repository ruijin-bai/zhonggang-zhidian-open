"""DTOs for the business-matter execution workflow."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.scenario import BusinessScenario


class BusinessCaseCreate(BaseModel):
    scenario: BusinessScenario
    title: str = Field(min_length=2, max_length=255)
    org_path: str | None = None
    project_code: str | None = Field(default=None, max_length=64)
    amount_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    facts: dict = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class BusinessCaseReviewRequest(BaseModel):
    confirmed: bool
    note: str = Field(min_length=1, max_length=512)
    # 复核结论必须产出可执行的审批路径，否则复核=白复核
    approver_path: list[str] = Field(default_factory=list)
    required_materials: list[str] = Field(default_factory=list)

    @field_validator("note")
    @classmethod
    def meaningful_note(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("请填写实际复核意见或补充要求")
        return text

    @field_validator("approver_path", "required_materials")
    @classmethod
    def meaningful_items(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def confirmed_path_required(self) -> "BusinessCaseReviewRequest":
        if self.confirmed and not self.approver_path:
            raise ValueError("确认办理口径时必须填写可执行的审批路径")
        return self


class BusinessCaseUpdate(BusinessCaseCreate):
    """Replace the editable facts of an owned draft or returned matter."""


class BusinessCaseOut(BaseModel):
    case_id: str
    case_no: str
    requester_id: str
    scenario: str
    title: str
    org_path: str
    org_name: str | None = None
    project_code: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    facts: dict = Field(default_factory=dict)
    status: str
    risk_level: str
    need_human: bool
    decision_summary: str | None = None
    decision_snapshot: dict = Field(default_factory=dict)
    evaluated_at: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
