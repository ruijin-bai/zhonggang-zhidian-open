"""DTOs for regulation change impact assessment."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChangeImpactItemOut(BaseModel):
    item_id: str
    item_type: str
    object_type: str
    object_id: str | None = None
    severity: str
    status: str
    old_snapshot: dict = Field(default_factory=dict)
    new_snapshot: dict = Field(default_factory=dict)
    resolution: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None


class ChangeImpactOut(BaseModel):
    impact_id: str
    new_file_id: str
    old_file_id: str | None = None
    new_file_title: str = ""
    new_file_version: str = ""
    old_file_title: str | None = None
    old_file_version: str | None = None
    status: str
    summary: dict = Field(default_factory=dict)
    generated_by: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    confirmation_note: str | None = None
    items: list[ChangeImpactItemOut] = Field(default_factory=list)


class ImpactResolveRequest(BaseModel):
    resolution: str = Field(min_length=1, max_length=4000)


class ImpactConfirmRequest(BaseModel):
    note: str = Field(default="", max_length=512)
