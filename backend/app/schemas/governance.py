"""DTOs for accountable governance work queues."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


class GovernanceTaskAction(BaseModel):
    action: str
    note: str = Field(default="", max_length=1000)
    due_date: date | None = None

    @model_validator(mode="after")
    def validate_action(self):
        if self.action not in {"claim", "release", "resolve", "dismiss", "reopen"}:
            raise ValueError("不支持的任务操作")
        if self.action in {"resolve", "dismiss"} and not self.note.strip():
            raise ValueError("完成或关闭任务必须填写处理依据")
        return self
