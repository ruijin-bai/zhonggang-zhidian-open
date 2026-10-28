"""Synthetic evidence-contract checks, never counted as real competition samples."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.db.models.qa import QASession
from app.db.models.rule import DecisionRule
from app.db.models.trial import TrialBenchmarkRecord, TrialUsageEvent
from app.db.models.user import User
from app.services.competition import evidence
from app.services.trial import build_trial_summary
from test_asset_rule_evidence import _setup
from test_business_golden_eval import _case


async def test_trial_rates_use_owned_answered_non_evaluation_sessions_once(session):
    owner = User(user_id="evidence-owner", username="evidence-owner", hashed_password="unused", role="R1")
    other = User(user_id="evidence-other", username="evidence-other", hashed_password="unused", role="R1")
    session.add_all([owner, other])
    await session.flush()
    session.add_all([
        QASession(session_id="answer-a", user_id=owner.user_id, question="合成问题A", answer_interpret="合成回答A"),
        QASession(session_id="answer-b", user_id=owner.user_id, question="合成问题B", answer_interpret="合成降级回答B", degraded=True),
        QASession(session_id="followup", user_id=owner.user_id, question="合成未完成追问"),
        QASession(session_id="eval", user_id=owner.user_id, question="合成评测", answer_interpret="评测回答", is_evaluation=True),
        QASession(session_id="foreign", user_id=other.user_id, question="他人问题", answer_interpret="他人回答"),
        QASession(session_id="orphan", user_id=owner.user_id, question="未参加试用的问题", answer_interpret="已有回答"),
    ])
    await session.flush()
    now = datetime.now(timezone.utc)
    def event(kind, sid, **kwargs):
        values = dict(user_id=owner.user_id, role="R1", session_id=sid, event_type=kind, is_trial=True)
        values.update(kwargs)
        return TrialUsageEvent(**values)
    session.add_all([
        event("qa_completed", "answer-a", result_state="completed", latency_total_ms=3000, created_at=now-timedelta(seconds=1)),
        event("qa_completed", "answer-a", result_state="completed", latency_total_ms=1200, created_at=now),
        event("qa_completed", "answer-b", result_state="degraded", latency_total_ms=2400),
        event("qa_completed", "followup", result_state="completed"),
        event("qa_completed", "eval", result_state="completed"),
        event("qa_completed", "foreign", result_state="completed"),
        event("qa_completed", None, result_state="completed"),
        event("qa_completed", "missing", result_state="completed"),
        event("feedback_like", "answer-a"), event("feedback_like", "answer-a"),
        event("feedback_like", "answer-a", user_id=other.user_id),
        event("feedback_like", "orphan"), event("feedback_like", "eval"),
        event("feedback_correct", "answer-b"), event("feedback_correct", "answer-b"),
        event("citation_opened", "answer-a"), event("citation_opened", "answer-a"),
        event("manual_review_requested", "answer-b"), event("manual_review_requested", "answer-b"),
    ])
    await session.commit()
    summary = await build_trial_summary(session)
    assert summary["trial_participants"] == 1
    assert summary["real_questions"] == 2
    assert summary["avg_total_latency_ms"] == 1800
    for key in ["question_completion_rate", "positive_feedback_rate", "correction_rate", "citation_open_rate", "manual_review_rate"]:
        assert summary[key] == 0.5


async def test_orphan_trial_actions_do_not_invent_participants_or_zero_percent_metrics(session):
    owner = User(user_id="orphan-owner", username="orphan-owner", hashed_password="unused", role="R1")
    session.add(owner)
    await session.flush()
    session.add(TrialUsageEvent(user_id=owner.user_id, role="R1", event_type="feedback_like", is_trial=True))
    await session.commit()
    summary = await build_trial_summary(session)
    assert summary["trial_participants"] == summary["real_questions"] == 0
    assert summary["positive_feedback_rate"] is summary["avg_total_latency_ms"] is None


async def test_fast_failed_task_is_not_reported_as_time_saved(session):
    session.add_all([
        TrialBenchmarkRecord(scenario="合成测试", participant_id_hash="a"*64, manual_duration_seconds=100, ai_duration_seconds=150, manual_success=True, ai_success=True, manual_source_found=True, ai_source_found=True),
        TrialBenchmarkRecord(scenario="合成测试", participant_id_hash="b"*64, manual_duration_seconds=100, ai_duration_seconds=1, manual_success=True, ai_success=False, manual_source_found=True, ai_source_found=False),
    ])
    await session.commit()
    summary = await build_trial_summary(session)
    assert summary["benchmark_records"] == 2
    assert summary["comparable_benchmark_records"] == 1
    assert summary["ai_avg_seconds"] == 150
    assert summary["avg_saved_seconds"] == -50
    assert summary["efficiency_improvement_rate"] == -0.5


async def test_evidence_counts_reviewed_v2_sources_and_excludes_future_and_unsigned_rules(session):
    _employee, reviewer, _curator, unit, _asset, version, *_ = await _setup(session)
    stamp = datetime.now(timezone.utc)
    session.add_all([
        DecisionRule(rule_key="synthetic-reviewed", scenario="contract_change", source_kind="asset", asset_version_id=version.version_id, retrieval_unit_id=unit.unit_id, status="current", reviewed_by=reviewer.user_id, reviewed_at=stamp),
        DecisionRule(rule_key="synthetic-unsigned", scenario="contract_change", source_kind="asset", asset_version_id=version.version_id, retrieval_unit_id=unit.unit_id, status="current"),
        DecisionRule(rule_key="synthetic-future", scenario="contract_change", source_kind="asset", asset_version_id=version.version_id, retrieval_unit_id=unit.unit_id, status="current", reviewed_by=reviewer.user_id, reviewed_at=stamp, effective_from=date.today()+timedelta(days=1)),
    ])
    await session.commit()
    result = await evidence.build_competition_evidence(session)
    coverage = result["rule_coverage"]
    assert coverage["current_rules"] == 2
    assert coverage["verified_source_rules"] == 1
    assert coverage["covered_regulations"] == 1
    assert coverage["verified_source_rate"] == 0.5


def _golden_paths(monkeypatch, tmp_path, cases, result=None):
    dataset = tmp_path / "golden.json"
    output = tmp_path / "result.json"
    dataset.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    if result is not None:
        output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(evidence, "GOLDEN_PATH", dataset)
    monkeypatch.setattr(evidence, "GOLDEN_RESULT_PATH", output)
    return dataset, output


@pytest.mark.parametrize("changes", [
    {"reviewer": ""}, {"reviewer": None}, {"reviewed_at": "not-a-date"},
    {"reviewed_at": (date.today()+timedelta(days=1)).isoformat()}, {"id": "draft"},
    {"expected_sources": [{"regulation_code": "CHEC-001"}]},
    {"facts": None}, {"expected_need_human": "false"}, {"expected_claims": [None]},
])
def test_golden_count_requires_complete_expert_signoff_fields(monkeypatch, tmp_path, changes):
    cases = [_case() | changes]
    _golden_paths(monkeypatch, tmp_path, cases)
    result = evidence.golden_evidence()
    assert result["registered_case_total"] == result["unsigned_or_invalid_total"] == 1
    assert result["expert_reviewed_total"] == 0
    assert result["result_available"] is False
    assert result["metrics"] is None


def test_duplicate_signed_ids_do_not_double_count_expert_samples(monkeypatch, tmp_path):
    _golden_paths(monkeypatch, tmp_path, [_case(), _case()])
    result = evidence.golden_evidence()
    assert result["registered_case_total"] == result["unsigned_or_invalid_total"] == 2
    assert result["expert_reviewed_total"] == 0


def test_golden_result_requires_exact_dataset_hash_and_ids(monkeypatch, tmp_path):
    cases = [_case()]
    digest = hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    result = {"dataset": "golden_business_qa", "metric_scope": "business_answer_quality", "expert_reviewed_total": 1, "golden_dataset_sha256": digest, "business_answer_accuracy": 1.0, "details": [{"id": "G001"}]}
    dataset, output = _golden_paths(monkeypatch, tmp_path, cases, result)
    assert evidence.golden_evidence()["result_available"] is True
    output.write_text(json.dumps(result | {"details": [{"id": "G999"}]}), encoding="utf-8")
    assert evidence.golden_evidence()["result_available"] is False
    output.write_text(json.dumps(result), encoding="utf-8")
    dataset.write_text(json.dumps([_case() | {"question": "修改后的同编号问题"}]), encoding="utf-8")
    assert evidence.golden_evidence()["expert_reviewed_total"] == 1
    assert evidence.golden_evidence()["result_available"] is False
