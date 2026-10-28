"""Audit logging helper (NFR-06) — full retention of QA and operations."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    actor_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit record (best-effort; never raises to the caller)."""
    try:
        session.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail,
                ip=ip,
            )
        )
        await session.flush()
    except Exception:  # noqa: BLE001
        pass
