"""Push DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class PushNotifyRequest(BaseModel):
    file_id: str
    require_review: bool = True
    target_role: str | None = None
    scenario_tag: str | None = None
    old_file_id: str | None = None


class PushRecordOut(BaseModel):
    push_id: str
    file_id: str | None = None
    target_role: str | None = None
    scenario_tag: str | None = None
    status: str
    digest: str
    created_by: str | None = None
    read_count: int = 0
    unread_count: int = 0
    push_time: str | None = None


class PushCenterOut(BaseModel):
    pushes: list[PushRecordOut] = []
    total_unread: int = 0


class ReceiptUpdate(BaseModel):
    read: bool = True


class ReceiptBatchUpdate(BaseModel):
    push_ids: list[str] | None = None
    read: bool = True
