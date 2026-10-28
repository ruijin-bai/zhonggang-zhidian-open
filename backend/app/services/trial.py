"""Aggregate real trial evidence without inventing missing samples."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.trial import TrialBenchmarkRecord, TrialUsageEvent
from app.db.models.qa import QASession


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


async def build_trial_summary(db: AsyncSession) -> dict:
    # Declaring a trial event cannot create a business question. It must join
    # its author's real, answered session, and feedback must join that cohort.
    events = list((await db.execute(select(TrialUsageEvent).join(
        QASession, (TrialUsageEvent.session_id == QASession.session_id)
        & (TrialUsageEvent.user_id == QASession.user_id)
    ).where(
        TrialUsageEvent.is_trial.is_(True), QASession.is_evaluation.is_(False),
        func.trim(QASession.answer_interpret, " \n\r\t") != "",
    ).order_by(TrialUsageEvent.created_at.desc(), TrialUsageEvent.event_id.desc()))).scalars())
    completed = {}
    for event in events:
        if event.event_type == "qa_completed" and event.result_state in {"completed", "degraded"}:
            completed.setdefault(event.session_id, event)
    questions = len(completed)
    participants = len({event.user_id for event in completed.values()})
    completed_ok = sum(event.result_state == "completed" for event in completed.values())

    def action_count(event_type):
        return len({event.session_id for event in events if event.event_type == event_type and event.session_id in completed})

    def average_latency(field):
        values = [getattr(event, field) for event in completed.values() if getattr(event, field) is not None]
        return round(sum(values) / len(values), 1) if values else None

    citations = action_count("citation_opened")
    likes = action_count("feedback_like")
    corrections = action_count("feedback_correct")
    need_human = action_count("manual_review_requested")
    first_ms = average_latency("latency_first_token_ms")
    total_ms = average_latency("latency_total_ms")
    benchmark_total = int((await db.execute(select(func.count()).select_from(TrialBenchmarkRecord))).scalar() or 0)
    benchmark = (
        await db.execute(
            select(
                func.count(),
                func.avg(TrialBenchmarkRecord.manual_duration_seconds),
                func.avg(TrialBenchmarkRecord.ai_duration_seconds),
            ).select_from(TrialBenchmarkRecord).where(
                TrialBenchmarkRecord.manual_success.is_(True), TrialBenchmarkRecord.ai_success.is_(True),
                TrialBenchmarkRecord.manual_source_found.is_(True), TrialBenchmarkRecord.ai_source_found.is_(True),
            )
        )
    ).one()
    comparable_benchmarks, manual_avg, ai_avg = benchmark
    manual_avg_value = round(float(manual_avg), 2) if manual_avg is not None else None
    ai_avg_value = round(float(ai_avg), 2) if ai_avg is not None else None
    saved = (
        round(manual_avg_value - ai_avg_value, 2)
        if manual_avg_value is not None and ai_avg_value is not None
        else None
    )
    improvement = (
        round((manual_avg_value - ai_avg_value) / manual_avg_value, 4)
        if manual_avg_value and ai_avg_value is not None
        else None
    )
    return {
        "sample_kind": "real_trial_only",
        "disclaimer": "仅统计试用事件关联的本人非评测、已有回答会话，按会话去重；追问未完成、缺失会话与评测记录不计入。试用记录仍需业务核对，不代表正式生产成效。",
        "question_scope": "unique_answered_trial_sessions",
        "trial_participants": int(participants or 0),
        "real_questions": int(questions or 0),
        "question_completion_rate": _rate(completed_ok, int(questions or 0)),
        "manual_review_rate": _rate(int(need_human or 0), int(questions or 0)),
        "citation_open_rate": _rate(int(citations or 0), int(questions or 0)),
        "positive_feedback_rate": _rate(int(likes or 0), int(questions or 0)),
        "correction_rate": _rate(int(corrections or 0), int(questions or 0)),
        "avg_first_token_ms": round(float(first_ms), 1) if first_ms is not None else None,
        "avg_total_latency_ms": round(float(total_ms), 1) if total_ms is not None else None,
        "benchmark_records": int(benchmark_total or 0),
        "comparable_benchmark_records": int(comparable_benchmarks or 0),
        "timing_scope": "both_tasks_successful_with_sources",
        "manual_avg_seconds": manual_avg_value,
        "ai_avg_seconds": ai_avg_value,
        "avg_saved_seconds": saved,
        "efficiency_improvement_rate": improvement,
    }
