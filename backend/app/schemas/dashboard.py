"""Dashboard / quality metrics DTOs."""
from __future__ import annotations

from pydantic import BaseModel


class QualityDashboard(BaseModel):
    case_total: int = 0
    case_review_required: int = 0
    case_confirmed: int = 0
    active_rule_count: int = 0
    open_impact_count: int = 0
    open_high_impact_count: int = 0
    qa_total: int = 0
    answered_total: int = 0
    evaluation_run_total: int = 0
    recall_rate: float | None = None
    citation_rate: float | None = None
    adopt_rate: float | None = None
    human_handoff_rate: float | None = None
    # 实时质量信号：基于在线问答会话统计，不依赖评估回放。
    realtime_citation_rate: float | None = None
    realtime_avg_confidence: float | None = None
    degraded_rate: float | None = None
    grounding_rate: float | None = None
    authority_answer_rate: float | None = None
    correction_distribution: list = []
    uncovered_scenarios: list = []
    # 制度治理面：领导要看制度资产的全貌与健康度
    regulation_total: int = 0
    regulation_current: int = 0
    regulation_pending_review: int = 0
    pending_asset_reviews: int = 0
    clause_total: int = 0
    regulation_with_clauses: int = 0  # 已完成内容解析的制度数
    pending_feedback_count: int = 0  # 未处理的员工纠错
    regulation_authority_verified: int = 0
    source_anchor_rate: float | None = None
    testset_total: int = 0
    retrieval_smoke_total: int = 0
    evaluation_grounding_rate: float | None = None
    evaluation_answer_rate: float | None = None
    evaluation_authority_rate: float | None = None
