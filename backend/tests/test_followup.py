"""Smart follow-up slot detection tests (T09)."""
from __future__ import annotations

from types import SimpleNamespace

from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.services.qa_service import QAService
from app.services.rag.followup import FollowUpService
from app.services.rag.retriever import RetrievedClause


def test_detect_slots_from_question():
    svc = FollowUpService()
    filled = svc.detect_slots("境外项目变更款50万美元由谁审批？")
    assert filled["amount"] == "50万"
    assert filled["domestic"] == "境外"
    assert "level" not in filled  # 审批层级由规则计算，不再要求用户猜测


def test_missing_slots_triggers_followup():
    svc = FollowUpService()
    filled = svc.detect_slots("境外项目变更款50万美元由谁审批？")
    missing = svc.missing_slots("境外项目变更款50万美元由谁审批？", filled, round_no=1)
    assert missing == []
    fu = svc.build_followup(missing, 1)
    assert fu["round"] == 1
    assert fu["prompts"] == []


def test_grade_duration_requires_target_subgrade_and_starting_experience():
    svc = FollowUpService()
    filled = svc.detect_slots("M2到M5最短时间")
    missing = svc.missing_slots("M2到M5最短时间", filled, round_no=1)
    assert missing == ["target_grade", "current_experience"]
    followup = svc.build_followup(missing, 1)
    assert followup["prompts"][0]["options"] == ["M5-1", "M5-2"]


def test_explicit_grade_duration_context_does_not_repeat_followup():
    svc = FollowUpService()
    text = "M2到M5-2最短时间，已有3年工作经验"
    filled = svc.detect_slots(text)
    assert filled["target_grade"] == "M5-2"
    assert filled["current_experience"] == "3年"
    assert svc.missing_slots(text, filled, round_no=1) == []


def test_non_approval_question_no_followup():
    svc = FollowUpService()
    filled = svc.detect_slots("差旅费报销需要哪些材料？")
    missing = svc.missing_slots("差旅费报销需要哪些材料？", filled, 1)
    assert missing == []


async def test_governed_grade_slots_are_not_overwritten_by_dynamic_llm(session, monkeypatch):
    service = QAService()
    file = RegulationFile(
        file_id="f_grade", title="中国港湾领导人员管理办法", org_path="/",
        secret_level="internal", domain="*", status="current",
    )
    clause = Clause(
        clause_id="c_grade", file_id="f_grade", clause_no="第七条",
        content="担任M4级一般应具有担任M3级1年以上工作经历。",
        status="current",
    )
    candidates = [RetrievedClause(clause=clause, file=file, score=0.9)]

    async def fake_retrieve(*args, **kwargs):
        return candidates

    async def fake_rerank(*args, **kwargs):
        return candidates

    async def dynamic_must_not_run(*args, **kwargs):
        raise AssertionError("deterministic slots must bypass dynamic follow-up")

    monkeypatch.setattr(service.retriever, "retrieve", fake_retrieve)
    monkeypatch.setattr(service.retriever, "rerank", fake_rerank)
    monkeypatch.setattr(service.followup, "dynamic_followup", dynamic_must_not_run)

    events = []
    async for event in service.ask_stream(
        session,
        user=SimpleNamespace(user_id="u_test"),
        permissions=[],
        question="M2到M5最短时间",
        round_no=1,
    ):
        events.append(event)

    followup = next(event["data"] for event in events if event["type"] == "followup")
    assert followup["missing"] == ["target_grade", "current_experience"]
