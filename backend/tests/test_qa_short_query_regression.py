"""Regression coverage for short grade-code questions that previously retrieved noise."""

from app.services.qa_service import _merge_retrieval_query
from app.services.rag.retriever import _topic_hints


def test_rewrite_keeps_original_grade_code() -> None:
    merged = _merge_retrieval_query("M2的工资多少", "岗位基薪标准是多少")
    assert merged.startswith("M2的工资多少 ")
    assert "岗位基薪" in merged


def test_salary_question_routes_to_salary_source_family() -> None:
    assert "薪酬" in _topic_hints("M2的工资多少")
    assert "领导人员" not in _topic_hints("M2的工资多少")


def test_grade_progression_question_routes_to_leadership_rules() -> None:
    assert "领导人员" in _topic_hints("M2到M5最短时间")
