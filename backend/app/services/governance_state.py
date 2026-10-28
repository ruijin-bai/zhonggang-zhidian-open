"""Usable source confirmation; formal metadata and maintainer attestation differ."""
from __future__ import annotations

from datetime import datetime

from app.db.models.regulation import RegulationFile


def authority_gaps(item: RegulationFile) -> list[str]:
    gaps: list[str] = []
    code = (item.regulation_code or "").strip()
    if not code or code == (item.title or "").strip():
        gaps.append("regulation_code")
    if item.effective_date is None:
        gaps.append("effective_date")
    if not item.owner_org:
        gaps.append("owner_org")
    if not item.domain or item.domain == "*":
        gaps.append("domain")
    return gaps


def valid_source_confirmation(statement: dict | None) -> bool:
    if not isinstance(statement, dict) or statement.get("kind") != "maintainer" or statement.get("confirmed") is not True:
        return False
    if not all(isinstance(statement.get(key), str) and statement[key].strip() for key in ("actor_id", "confirmed_at", "note")):
        return False
    try:
        return datetime.fromisoformat(statement["confirmed_at"].replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def source_verification(item: RegulationFile) -> str:
    statement = getattr(item, "source_confirmation", None)
    if valid_source_confirmation(statement):
        matches = all(statement.get(key, getattr(item, attribute, None)) == getattr(item, attribute, None)
            for key, attribute in (("file_id", "file_id"), ("version", "version"), ("object_key", "object_key")))
        if statement.get("version_id"):
            matches = matches and statement["version_id"] == getattr(item, "source_version_id", None)
        if matches:
            return "maintainer"
    return "metadata" if not authority_gaps(item) else "unconfirmed"


def is_authority_verified(item: RegulationFile) -> bool:
    # Retained API name for compatibility. This is source readiness, not a
    # claim that a department or the competition office approved the material.
    return item.status == "current" and source_verification(item) != "unconfirmed"
