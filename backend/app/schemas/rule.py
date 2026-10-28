"""DTOs for governed decision rules."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.scenario import BusinessScenario


class DecisionRuleCreate(BaseModel):
    rule_key: str = Field(min_length=2, max_length=96)
    scenario: BusinessScenario
    rule_type: str = "approval"
    priority: int = Field(default=100, ge=0, le=10000)
    source_kind: Literal["regulation", "asset"] = "regulation"
    file_id: str | None = None
    clause_id: str | None = None
    asset_version_id: str | None = None
    retrieval_unit_id: str | None = None
    currency: str = "*"
    amount_min_minor: int | None = Field(default=None, ge=0)
    amount_max_minor: int | None = Field(default=None, ge=0)
    min_inclusive: bool = True
    max_inclusive: bool = True
    org_scope: str = "/"
    conditions: dict = Field(default_factory=dict)
    approver_path: list[str] = Field(default_factory=list)
    required_materials: list[str] = Field(default_factory=list)
    risk_note: str | None = Field(default=None, max_length=4000)
    effective_from: date | None = None
    effective_to: date | None = None
    activate_now: bool = False
    activation_note: str = Field(default="", max_length=512)

    @field_validator("approver_path", "required_materials")
    @classmethod
    def strip_items(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper() or "*"

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.source_kind == "regulation":
            if not self.file_id or not self.clause_id or self.asset_version_id or self.retrieval_unit_id:
                raise ValueError("制度规则必须明确制度与条款，不能混用资料证据")
        elif not self.asset_version_id or not self.retrieval_unit_id or self.file_id or self.clause_id:
            raise ValueError("资料规则必须明确发布版本与引用单元，不能混用旧条款")
        if (self.amount_min_minor is not None or self.amount_max_minor is not None) and self.currency == "*":
            raise ValueError("涉及金额边界的规则须明确币种；不涉及金额判断时币种可留空")
        if self.amount_min_minor is not None and self.amount_max_minor is not None:
            if self.amount_min_minor > self.amount_max_minor:
                raise ValueError("金额下限不能大于上限")
        if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
            raise ValueError("规则失效日期不能早于生效日期")
        if not self.approver_path:
            raise ValueError("审批路径不能为空")
        if self.activate_now and not self.activation_note.strip():
            raise ValueError("本人启用规则须明确确认已对照原文")
        return self


class DecisionRuleReviewRequest(BaseModel):
    approved: bool
    note: str = Field(default="", max_length=512)


class DecisionRuleOut(BaseModel):
    rule_id: str
    rule_key: str
    scenario: str
    rule_type: str
    priority: int
    status: str
    file_id: str
    clause_id: str
    source_kind: str = "regulation"
    asset_version_id: str | None = None
    retrieval_unit_id: str | None = None
    file_title: str = ""
    clause_no: str = ""
    currency: str
    amount_min_minor: int | None = None
    amount_max_minor: int | None = None
    min_inclusive: bool
    max_inclusive: bool
    org_scope: str
    org_name: str | None = None
    conditions: dict = Field(default_factory=dict)
    approver_path: list[str] = Field(default_factory=list)
    required_materials: list[str] = Field(default_factory=list)
    risk_note: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
