import httpx
import json

from app.core.security import hash_password
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token
from app.services.competition.evidence import (
    build_award_readiness,
    build_competition_evidence,
    golden_evidence,
    migration_source_info,
)
from scripts.export_competition_evidence import _safe_model_runtime_summary


async def test_competition_evidence_keeps_missing_real_metrics_empty(session):
    result = await build_competition_evidence(session)
    assert result["trial"]["efficiency_improvement_rate"] is None
    assert result["golden"]["expert_reviewed_total"] == 0
    assert result["golden"]["metrics"] is None
    assert result["engineering"]["backend_tests_passed"] is None
    assert result["award_readiness"]["all_passed"] is False
    assert result["award_readiness"]["gate_total"] == 6


def test_award_readiness_requires_real_thresholds_and_names_business_owners():
    result = build_award_readiness(
        {"trial_participants": 20, "real_questions": 50, "benchmark_records": 30},
        {"expert_reviewed_total": 30},
        {"featured_scenarios_passed": 3, "verified_source_rules": 3},
    )
    assert result["all_passed"] is True
    assert result["passed_total"] == result["gate_total"] == 6
    assert all(item["owner"] and item["action"] for item in result["items"])


def test_competition_evidence_reports_single_migration_head():
    result = migration_source_info()
    assert result["single_root_single_head"] is True
    assert result["heads"] == ["0021"]
    assert golden_evidence()["result_available"] is False


def test_model_runtime_evidence_export_is_strictly_whitelisted(tmp_path):
    source = tmp_path / "model_runtime.json"
    source.write_text(json.dumps({
        "all_passed": True,
        "component_checks_passed": True,
        "qa_chain_passed": True,
        "component_runs": 1,
        "secret": "sk-do-not-export",
        "checks": {
            "QA_SMOKE": {
                "status": "PASS",
                "prompt": "内部制度正文",
                "runs": [{
                    "run": 1, "status": "PASS", "latency_ms": 100,
                    "degraded": False, "need_human": True,
                    "provider_body": "sensitive",
                }],
            },
        },
    }), encoding="utf-8")
    summary = _safe_model_runtime_summary(source)
    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["qa_chain_passed"] is True
    assert summary["checks"]["QA_SMOKE"]["runs"][0]["need_human"] is True
    assert "sk-do-not-export" not in serialized
    assert "内部制度正文" not in serialized
    assert "sensitive" not in serialized


async def test_competition_evidence_endpoint_is_r4_only(session):
    r1 = User(user_id="evidence_r1", username="evidence_r1", hashed_password=hash_password("Password@123"), role="R1")
    r4 = User(user_id="evidence_r4", username="evidence_r4", hashed_password=hash_password("Password@123"), role="R4")
    session.add_all([r1, r4])
    await session.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/api/v1/competition/evidence", headers={"Authorization": f"Bearer {issue_token(r1)}"})
        allowed = await client.get("/api/v1/competition/evidence", headers={"Authorization": f"Bearer {issue_token(r4)}"})
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["data"]["golden"]["expert_reviewed_total"] == 0
