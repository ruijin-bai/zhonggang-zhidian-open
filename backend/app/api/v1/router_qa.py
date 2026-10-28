"""QA endpoints: ask (RAG), feedback, session detail."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_user_context, require_roles
from app.core.exceptions import ForbiddenError, ok, NotFoundError
from app.db.models.feedback import QAFeedback
from app.db.models.qa import QACitation, QASession
from app.db.models.business_case import BusinessCase
from app.db.session import get_db
from app.schemas.qa import CitationOut, FollowUpOut, QAAskRequest, QAAskResponse, FeedbackRequest
from app.services.audit import record_audit
from app.services.qa_service import QAService

router = APIRouter(prefix="/qa", tags=["qa"])


@router.post("/ask", response_model=None)
async def ask(
    body: QAAskRequest,
    req: Request,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, permissions = ctx
    if body.evaluation and user.role != "R4":
        raise ForbiddenError("仅系统管理员可发起评测流量")
    service = QAService()
    result = await service.ask(
        db,
        user=user,
        permissions=permissions,
        question=body.question,
        slots=body.slots or {},
        session_id=body.session_id,
        round_no=body.round,
        client_ip=req.client.host if req.client else None,
        is_evaluation=body.evaluation,
    )
    await db.commit()

    citations = [CitationOut(**c) for c in result["citations"]]
    follow_up = FollowUpOut(**result["follow_up"]) if result["follow_up"] else None
    return ok(
        QAAskResponse(
            session_id=result["session_id"],
            answer_interpret=result["answer_interpret"],
            citations=citations,
            confidence=result["confidence"],
            degraded=result["degraded"],
            degraded_reason=result.get("degraded_reason"),
            follow_up=follow_up,
            need_human=result["need_human"],
            grounding_passed=result["grounding_passed"],
            grounding_coverage=result["grounding_coverage"],
            authority_verified=result["authority_verified"],
            quality_warnings=result["quality_warnings"],
        ).model_dump()
    )


@router.post("/ask/stream", response_model=None)
async def ask_stream(
    body: QAAskRequest,
    req: Request,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Streaming QA endpoint (NDJSON event stream, fixes the answer timeout).

    Emits one JSON object per line: phase / retrieve / followup / delta / citations
    / confidence / done / error. The async generator inside commits the session,
    so no outer commit is needed.
    """
    user, permissions = ctx
    if body.evaluation and user.role != "R4":
        raise ForbiddenError("仅系统管理员可发起评测流量")
    service = QAService()

    async def event_generator():
        try:
            async for ev in service.ask_stream(
                db,
                user=user,
                permissions=permissions,
                question=body.question,
                slots=body.slots or {},
                session_id=body.session_id,
                round_no=body.round,
                client_ip=req.client.host if req.client else None,
                is_evaluation=body.evaluation,
            ):
                yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            yield (json.dumps({"type": "error", "message": f"问答服务异常：{exc}"}, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/feedback", response_model=None)
async def feedback(
    body: FeedbackRequest,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    user, _ = ctx
    session = await db.get(QASession, body.session_id)
    # Feedback is part of a user's own QA record.  Returning the same not-found
    # response for a foreign session prevents both tampering and ID discovery.
    if session is None or session.user_id != user.user_id:
        raise NotFoundError("问答会话不存在")
    fb = QAFeedback(session_id=body.session_id, user_id=user.user_id, type=body.type, content=body.content)
    db.add(fb)
    await db.flush()
    await db.commit()
    return ok({"fb_id": fb.fb_id})


class FeedbackResolveRequest(BaseModel):
    note: str = ""


@router.get("/feedbacks", response_model=None)
async def list_feedbacks(
    resolved: bool | None = None,
    _: object = Depends(require_roles("R2", "R4")),
    db: AsyncSession = Depends(get_db),
):
    """R2/R4 纠错反馈处理队列：员工纠错必须有人接，闭环不允许断。"""
    stmt = (
        select(QAFeedback, QASession.question, QASession.answer_interpret)
        .join(QASession, QAFeedback.session_id == QASession.session_id)
        .where(QAFeedback.type == "correct", QASession.is_evaluation.is_(False))
        .order_by(QAFeedback.created_at.desc())
        .limit(200)
    )
    if resolved is not None:
        stmt = stmt.where(QAFeedback.resolved == resolved)
    rows = (await db.execute(stmt)).all()
    return ok(
        [
            {
                "fb_id": fb.fb_id,
                "session_id": fb.session_id,
                "user_id": fb.user_id,
                "type": fb.type,
                "content": fb.content,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
                "resolved": fb.resolved,
                "resolved_by": fb.resolved_by,
                "resolved_note": fb.resolved_note,
                "resolved_at": fb.resolved_at.isoformat() if fb.resolved_at else None,
                "question": (question or "")[:120],
                "answer_excerpt": (answer or "")[:200] if answer else None,
            }
            for fb, question, answer in rows
        ]
    )


@router.post("/feedbacks/{fb_id}/resolve", response_model=None)
async def resolve_feedback(
    fb_id: str,
    body: FeedbackResolveRequest,
    reviewer=Depends(require_roles("R2", "R4")),
    db: AsyncSession = Depends(get_db),
):
    fb = await db.get(QAFeedback, fb_id)
    if fb is None:
        raise NotFoundError("反馈不存在")
    qa_session = await db.get(QASession, fb.session_id)
    if fb.type != "correct" or qa_session is None or qa_session.is_evaluation:
        raise NotFoundError("待处理纠错不存在")
    fb.resolved = True
    fb.resolved_by = reviewer.user_id
    fb.resolved_note = body.note.strip() or None
    fb.resolved_at = datetime.now(timezone.utc)
    await record_audit(
        db, actor_id=reviewer.user_id, action="qa.feedback.resolved", target_type="qa_feedback", target_id=fb.fb_id
    )
    await db.commit()
    return ok({"fb_id": fb.fb_id, "resolved": True})


@router.get("/sessions", response_model=None)
async def my_sessions(
    keyword: str = Query(default="", max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    """Search only the caller's actual consultation records, never evaluation traffic."""
    user, _ = ctx
    filters = [QASession.user_id == user.user_id, QASession.is_evaluation.is_(False)]
    if keyword.strip():
        filters.append(QASession.question.contains(keyword.strip(), autoescape=True))
    total = int((await db.execute(select(func.count()).select_from(QASession).where(*filters))).scalar() or 0)
    rows = list((await db.execute(select(QASession).where(*filters).order_by(QASession.created_at.desc(), QASession.session_id.desc()).offset(offset).limit(limit))).scalars())
    ids = [row.session_id for row in rows]
    linked = dict((await db.execute(select(BusinessCase.facts["source_session"].as_string(), func.count()).where(BusinessCase.requester_id == user.user_id, BusinessCase.facts["source_session"].as_string().in_(ids)).group_by(BusinessCase.facts["source_session"].as_string()))).all()) if ids else {}
    return ok({"items": [{
        "session_id": row.session_id, "question": row.question[:240],
        "answer_excerpt": (row.answer_interpret or "").strip()[:180],
        "completed": bool((row.answer_interpret or "").strip()),
        "need_human": row.need_human, "degraded": row.degraded,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "linked_case_count": linked.get(row.session_id, 0),
    } for row in rows], "total": total, "offset": offset, "limit": limit})


@router.get("/session/{session_id}", response_model=None)
async def session_detail(
    session_id: str,
    ctx=Depends(get_user_context),
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(QASession, session_id)
    user, _ = ctx
    # A QA session can contain sensitive questions and cited clauses; it is
    # visible only to its creator.  Keep the former not-found contract so an
    # unauthorised caller cannot distinguish an existing session ID.
    if session is None or session.user_id != user.user_id:
        raise NotFoundError("问答会话不存在")
    citations = list(
        (await db.execute(select(QACitation).where(QACitation.session_id == session_id))).scalars().all()
    )
    cases = list((await db.execute(select(BusinessCase).where(BusinessCase.requester_id == user.user_id, BusinessCase.facts["source_session"].as_string() == session_id).order_by(BusinessCase.created_at.desc()))).scalars())
    feedback_types = list((await db.execute(select(QAFeedback.type).where(QAFeedback.session_id == session_id, QAFeedback.user_id == user.user_id).distinct())).scalars())
    return ok(
        {
            "session_id": session.session_id,
            "question": session.question,
            "answer_interpret": session.answer_interpret,
            "confidence": session.confidence,
            "degraded": session.degraded,
            "need_human": session.need_human,
            "grounding_passed": session.grounding_passed,
            "grounding_coverage": session.grounding_coverage,
            "authority_verified": session.authority_verified,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "completed": bool((session.answer_interpret or "").strip()),
            "feedback_types": feedback_types,
            "related_cases": [{"case_id": case.case_id, "case_no": case.case_no, "title": case.title, "status": case.status} for case in cases],
            "citations": [
                {
                    "clause_id": c.clause_id,
                    "file_title": c.file_title,
                    "regulation_code": "",
                    "clause_no": c.clause_no,
                    "excerpt": c.excerpt,
                    "consistent": c.consistent,
                    "source_page": c.source_page,
                    "content_hash": c.content_hash,
                }
                for c in citations
            ],
        }
    )
