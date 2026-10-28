"""Relation & graph DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class RelationCreate(BaseModel):
    from_id: str
    to_id: str
    rel_type: str  # replace | subordinate | multi_constraint | conflict
    note: str | None = None
    confirmed_by: str | None = None


class RelationOut(BaseModel):
    rel_id: str
    from_id: str
    to_id: str
    rel_type: str
    note: str | None = None
    confirmed_by: str | None = None


class GraphOut(BaseModel):
    nodes: list = []
    edges: list = []
    conflicts: list = []
