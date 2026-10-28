"""Dashboard figures must describe authorised work and real sampled outcomes."""
from datetime import date, timedelta

import httpx
import pytest

from app.db.models.asset import AssetDocument, AssetVersion, AssetVersionDocument, ContentNode, DocumentParseRun, KnowledgeAsset, RetrievalUnit, RetrievalUnitSource
from app.db.models.business_case import BusinessCase
from app.db.models.clause import Clause
from app.db.models.eval import TestCase as EvaluationCase, TestRun as EvaluationRun
from app.db.models.feedback import QAFeedback
from app.db.models.impact import ChangeImpactItem, ChangeImpactRun
from app.db.models.ingestion import IngestionJob
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.push import PushReceipt, PushRecord
from app.db.models.qa import QACitation, QASession
from app.db.models.regulation import RegulationFile
from app.db.models.relation import Relation
from app.db.models.rule import DecisionRule
from app.db.models.user import User
from app.main import app
from app.services.auth.auth_service import issue_token


async def _user(session, role, scope="/a", domain="工程", clearance="internal"):
    user = User(user_id=f"dashboard-{role}", username=f"dashboard-{role}", hashed_password="unused", role=role, secret_clearance=clearance)
    session.add_all([user, Permission(role=role, org_scope=scope, secret_level=clearance, domain=domain)])
    await session.flush()
    return user


def _file(file_id, **overrides):
    values = dict(file_id=file_id, title=file_id, version="v1", org_path="/a", status="current", secret_level="internal", domain="工程")
    values.update(overrides)
    return RegulationFile(**values)


def _case(case_id, user, org_path="/a", status="review_required"):
    return BusinessCase(case_id=case_id, case_no=case_id, requester_id=user.user_id, title=case_id, scenario="contract_change", org_path=org_path, status=status)


async def _get(user, path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, headers={"Authorization": f"Bearer {issue_token(user)}"})


async def test_employee_summary_matches_visible_directory_and_personal_tasks(session):
    user = await _user(session, "R1")
    other = User(user_id="dashboard-other", username="dashboard-other", hashed_password="unused", role="R1")
    session.add_all([
        other, _file("visible"), _file("shared", org_path="/", secret_level="public"),
        _file("foreign", org_path="/b"), _file("secret", secret_level="confidential"),
        _file("other-domain", domain="财务"), _file("pending", status="pending_review"),
        _file("future", effective_date=date.today() + timedelta(days=1)),
        _file("expired", expiry_date=date.today() - timedelta(days=1)),
    ])
    await session.flush()
    session.add_all([
        _case("mine-draft", user, status="draft"), _case("mine-returned", user, status="returned"),
        _case("mine-review", user), _case("other-review", other),
        Relation(from_id="visible", to_id="foreign"),
        ChangeImpactRun(impact_id="impact-hidden-for-employee", new_file_id="visible"),
    ])
    for status in ["sent", "draft", "recalled"]:
        session.add(PushRecord(push_id=f"push-{status}", status=status, digest=status))
        session.add(PushReceipt(push_id=f"push-{status}", user_id=user.user_id, read_status="unread"))
    await session.flush()
    session.add(ChangeImpactItem(impact_id="impact-hidden-for-employee", item_type="clause_changed", object_type="clause", severity="high"))
    await session.commit()

    summary = await _get(user, "/api/v1/dashboard/workbench")
    directory = await _get(user, "/api/v1/regulations")
    assert summary.status_code == directory.status_code == 200
    data = summary.json()["data"]
    assert data["regulation_total"] == 2
    assert data["regulation_total"] == len(directory.json()["data"])
    assert data["my_case_total"] == data["my_case_open"] == 3
    assert data["unread_pushes"] == 1
    for key in ["impact_open", "relation_count", "active_rules", "pending_case_reviews", "pending_regulation_reviews", "pending_asset_reviews", "pending_rule_reviews", "pending_feedbacks", "ingestion_failures"]:
        assert data[key] == 0
    assert data["total_actions"] == 4
    assert (await _get(user, "/api/v1/dashboard/quality")).status_code == 403


async def test_curator_pending_rules_and_failed_ingestion_respect_source_permissions(session):
    user = await _user(session, "R3")
    session.add(OrgUnit(org_id="dashboard-owner", name="责任部门", path="/a"))
    await session.flush()
    session.add_all([
        _file("visible", regulation_code="CHEC-001", owner_org="dashboard-owner", effective_date=date.today()),
        _file("hidden", org_path="/b"), _file("failed", status="failed"),
        _file("hidden-failed", status="failed", org_path="/b"),
    ])
    session.add_all([
        Clause(clause_id="public-clause", file_id="visible", content="规则来源", secret_level="internal"),
        Clause(clause_id="secret-clause", file_id="visible", content="不应泄露", secret_level="confidential"),
        Clause(clause_id="foreign-clause", file_id="hidden", content="异组织", secret_level="internal"),
    ])
    await session.flush()
    session.add_all([
        DecisionRule(rule_key="pending", scenario="contract_change", file_id="visible", clause_id="public-clause"),
        DecisionRule(rule_key="secret", scenario="contract_change", file_id="visible", clause_id="secret-clause"),
        DecisionRule(rule_key="foreign", scenario="contract_change", file_id="hidden", clause_id="foreign-clause"),
        DecisionRule(rule_key="active", scenario="contract_change", file_id="visible", clause_id="public-clause", status="current"),
        DecisionRule(rule_key="future", scenario="contract_change", file_id="visible", clause_id="public-clause", status="current", effective_from=date.today() + timedelta(days=1)),
        DecisionRule(rule_key="expired", scenario="contract_change", file_id="visible", clause_id="public-clause", status="current", effective_to=date.today() - timedelta(days=1)),
        IngestionJob(file_id="visible", source_filename="recovered.docx", status="failed"),
        IngestionJob(file_id="failed", source_filename="failed.docx", status="failed"),
        IngestionJob(file_id="hidden-failed", source_filename="foreign.docx", status="failed"),
    ])
    await session.commit()
    response = await _get(user, "/api/v1/dashboard/workbench")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["pending_rule_reviews"] == 1
    assert data["active_rules"] == 1
    assert data["ingestion_failures"] == 1
    assert data["regulation_total"] == 2  # Curator directory includes failed records.
    assert data["pending_case_reviews"] == 0
    assert data["pending_asset_reviews"] == 0


async def test_workbench_counts_new_published_assets_once_without_drafts_or_legacy_copies(session):
    user = await _user(session, "R1")
    session.add(_file("existing"))
    await session.flush()
    for key, changes in [
        ("new", {}), ("copy", {"legacy_file_id": "existing"}),
        ("draft", {"release_state": "draft"}), ("unready", {"ingestion_state": "pending"}),
        ("future", {"effective_date": date.today() + timedelta(days=1)}),
        ("expired", {"expiry_date": date.today() - timedelta(days=1)}),
        ("foreign", {"org_path": "/b"}), ("secret", {"secret_level": "confidential"}),
    ]:
        asset = KnowledgeAsset(asset_type="management_method", title=key,
            org_path=changes.pop("org_path", "/a"), secret_level=changes.pop("secret_level", "internal"), domain="工程")
        session.add(asset)
        await session.flush()
        version_values = dict(release_state="current", ingestion_state="ready")
        version_values.update(changes)
        session.add(AssetVersion(asset_id=asset.asset_id, **version_values))
    await session.commit()
    summary = (await _get(user, "/api/v1/dashboard/workbench")).json()["data"]
    legacy = (await _get(user, "/api/v1/regulations")).json()["data"]
    assets = (await _get(user, "/api/v1/assets?published_only=true")).json()["data"]
    assert summary["regulation_total"] == len(legacy) + sum(not row["legacy_file_id"] for row in assets) == 2


@pytest.mark.parametrize("role,expected_count", [("R1", 7), ("R3", 8)])
async def test_workbench_replaces_only_empty_legacy_with_readable_compound_versions(session, role, expected_count):
    user = await _user(session, role)
    session.add_all([_file(key) for key in ["empty", "readable", "blocked", "secret-only", "original-only"]])
    session.add(_file("pending-readable", status="pending_review"))
    await session.flush()
    session.add(Clause(file_id="readable", content="现行可读正文", status="current", secret_level="internal"))
    session.add(Clause(file_id="pending-readable", content="待审原文保留", status="current", secret_level="internal"))
    for key, legacy_id, state, clearance in [
        ("sub-one", "empty", "ready", "internal"), ("sub-two", "empty", "ready", "internal"),
        ("duplicate", "readable", "ready", "internal"), ("unready", "blocked", "blocked", "internal"),
        ("restricted", "secret-only", "ready", "confidential"),
        ("published-pending-copy", "pending-readable", "ready", "internal"),
    ]:
        asset = KnowledgeAsset(asset_type="management_method", title=key, org_path="/a", domain="工程")
        session.add(asset)
        await session.flush()
        version = AssetVersion(asset_id=asset.asset_id, legacy_file_id=legacy_id, release_state="current", ingestion_state=state)
        document = AssetDocument(filename=f"{key}.docx", object_key=f"test/{key}", sha256="a" * 64)
        session.add_all([version, document])
        await session.flush()
        parse = DocumentParseRun(document_id=document.document_id, parser_name="test", source_hash="a" * 64, status="succeeded", is_current=True)
        session.add_all([parse, AssetVersionDocument(version_id=version.version_id, document_id=document.document_id, role="normative_body", normative=True)])
        await session.flush()
        unit = RetrievalUnit(version_id=version.version_id, unit_type="article", text="可读原文", content_hash="b" * 64, secret_level=clearance, status="verified")
        node = ContentNode(parse_run_id=parse.parse_run_id, document_id=document.document_id, node_type="article", order_path="1", text="可读原文", content_hash="b" * 64)
        session.add_all([unit, node])
        await session.flush()
        session.add(RetrievalUnitSource(unit_id=unit.unit_id, node_id=node.node_id))
    await session.commit()
    legacy = (await _get(user, "/api/v1/regulations")).json()["data"]
    assets = (await _get(user, "/api/v1/assets?published_only=true")).json()["data"]
    readable_ids = {row["file_id"] for row in legacy if row["status"] == "current" and row["clause_count"] > 0}
    included = [row for row in assets if not row["legacy_file_id"] or
        (row["legacy_file_id"] not in readable_ids and row["readable_unit_count"] > 0)]
    empty_ids = {row["file_id"] for row in legacy if row["clause_count"] == 0}
    replaced = {row["legacy_file_id"] for row in included if row["legacy_file_id"] in empty_ids}
    summary = (await _get(user, "/api/v1/dashboard/workbench")).json()["data"]
    assert summary["regulation_total"] == len(legacy) - len(replaced) + len(included) == expected_count
    assert {row["title"] for row in included} == {"sub-one", "sub-two", "published-pending-copy"}


async def test_reviewer_actions_are_scoped_and_org_prefix_is_not_a_sibling_match(session):
    user = await _user(session, "R2")
    session.add_all([_file("visible"), _file("second"), _file("hidden", org_path="/b"), _file("pending", status="pending_review")])
    await session.flush()
    session.add_all([
        _case("local", user), _case("child", user, org_path="/a/sub"),
        _case("sibling", user, org_path="/ab"), _case("foreign", user, org_path="/b"),
        Relation(from_id="visible", to_id="second"), Relation(from_id="visible", to_id="hidden"),
        ChangeImpactRun(impact_id="visible-impact", new_file_id="visible"),
        ChangeImpactRun(impact_id="hidden-impact", new_file_id="hidden"),
    ])
    await session.flush()
    session.add_all([
        ChangeImpactItem(impact_id="visible-impact", item_type="clause_changed", object_type="clause", severity="high"),
        ChangeImpactItem(impact_id="visible-impact", item_type="clause_changed", object_type="clause", status="resolved"),
        ChangeImpactItem(impact_id="hidden-impact", item_type="clause_changed", object_type="clause", severity="high"),
    ])
    await session.commit()
    data = (await _get(user, "/api/v1/dashboard/workbench")).json()["data"]
    assert data["pending_case_reviews"] == 2
    assert data["pending_regulation_reviews"] == 1
    assert data["relation_count"] == data["impact_open"] == 1
    quality = (await _get(user, "/api/v1/dashboard/quality")).json()["data"]
    assert quality["case_total"] == quality["case_review_required"] == 2
    assert quality["regulation_total"] == 3
    assert quality["open_high_impact_count"] == 1


async def test_pending_asset_badge_matches_review_queue_permissions_and_keeps_failed_submissions(session):
    user = await _user(session, "R2")
    for key, org, state in [("visible", "/a", "active"), ("foreign", "/b", "active"), ("inactive", "/a", "inactive")]:
        asset = KnowledgeAsset(asset_type="management_method", title=key, org_path=org, domain="工程", status=state)
        session.add(asset)
        await session.flush()
        session.add(AssetVersion(asset_id=asset.asset_id, release_state="pending_review", ingestion_state="failed"))
    await session.commit()
    data = (await _get(user, "/api/v1/dashboard/workbench")).json()["data"]
    queue = await _get(user, "/api/v1/assets/reviews/pending")
    assert queue.status_code == 200, queue.text
    assert data["pending_asset_reviews"] == len(queue.json()["data"]) == 1
    assert data["total_actions"] == 1


async def test_no_samples_are_null_instead_of_zero_percent(session):
    user = await _user(session, "R4", scope="/", domain="*", clearance="secret")
    await session.commit()
    response = await _get(user, "/api/v1/dashboard/quality")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["qa_total"] == data["answered_total"] == data["evaluation_run_total"] == 0
    for key in ["recall_rate", "citation_rate", "adopt_rate", "human_handoff_rate", "realtime_citation_rate", "realtime_avg_confidence", "degraded_rate", "grounding_rate", "authority_answer_rate", "source_anchor_rate", "evaluation_grounding_rate", "evaluation_answer_rate", "evaluation_authority_rate"]:
        assert data[key] is None, key


async def test_quality_denominators_ignore_replays_unanswered_citations_and_duplicate_likes(session):
    user = await _user(session, "R4", scope="/", domain="*", clearance="secret")
    live = QASession(session_id="answered", user_id=user.user_id, question="实际问题", answer_interpret="实际回答", confidence=0.0, grounding_passed=True)
    pending = QASession(session_id="pending", user_id=user.user_id, question="待追问", need_human=True)
    whitespace = QASession(session_id="whitespace", user_id=user.user_id, question="空白回答", answer_interpret=" \n ")
    replay = QASession(session_id="replay", user_id=user.user_id, question="评价问题", answer_interpret="评测回答", is_evaluation=True, need_human=True, degraded=True)
    session.add_all([live, pending, whitespace, replay, EvaluationCase(case_id="gold", question="签审题")])
    await session.flush()
    session.add_all([
        QACitation(session_id="answered", clause_id="source", excerpt="引用"),
        QACitation(session_id="pending", clause_id="source", excerpt="不能加入有回答分子"),
        QACitation(session_id="replay", clause_id="source", excerpt="评测引用"),
        QAFeedback(session_id="answered", user_id=user.user_id, type="like"),
        QAFeedback(session_id="answered", user_id=user.user_id, type="like"),
        QAFeedback(session_id="answered", user_id=user.user_id, type="favorite"),
        QAFeedback(session_id="answered", user_id=user.user_id, type="correct"),
        QAFeedback(session_id="replay", user_id=user.user_id, type="correct"),
        EvaluationRun(case_id="gold", session_id="replay", recall_match=True, citation_match=True),
        EvaluationRun(case_id="gold", session_id="replay", recall_match=False, citation_match=False),
    ])
    await session.commit()
    data = (await _get(user, "/api/v1/dashboard/quality")).json()["data"]
    assert data["qa_total"] == 3
    assert data["answered_total"] == 1
    assert data["evaluation_run_total"] == 2
    assert data["realtime_citation_rate"] == data["grounding_rate"] == data["adopt_rate"] == 1.0
    assert data["realtime_avg_confidence"] == data["degraded_rate"] == 0.0
    assert data["authority_answer_rate"] == 0.0
    assert data["recall_rate"] == data["citation_rate"] == 0.5
    assert data["human_handoff_rate"] == 0.333
    assert data["pending_feedback_count"] == 1
    assert {row["type"]: row["count"] for row in data["correction_distribution"]} == {"like": 2, "favorite": 1, "correct": 1}
    summary = (await _get(user, "/api/v1/dashboard/workbench")).json()["data"]
    assert summary["pending_feedbacks"] == 1


async def test_v2_rule_counts_require_visible_effective_normative_sources_and_deduplicate_nodes(session):
    user = await _user(session, "R3")
    session.add(OrgUnit(org_id="v2-dashboard-owner", name="责任部门", path="/a"))
    await session.flush()
    for key in ["visible", "future", "foreign", "informative"]:
        asset = KnowledgeAsset(asset_type="management_method", title=f"V2-{key}", org_path="/b" if key == "foreign" else "/a", domain="工程", owner_org="v2-dashboard-owner")
        session.add(asset)
        await session.flush()
        version = AssetVersion(asset_id=asset.asset_id, version_label="v1", release_state="current", ingestion_state="ready", issue_no=f"CHEC-{key}", effective_date=date.today() + timedelta(days=1 if key == "future" else 0))
        document = AssetDocument(filename=f"{key}.docx", object_key=f"local/{key}", sha256="a" * 64)
        session.add_all([version, document])
        await session.flush()
        parse = DocumentParseRun(document_id=document.document_id, parser_name="test", source_hash="a" * 64, status="succeeded", is_current=True)
        session.add_all([parse, AssetVersionDocument(version_id=version.version_id, document_id=document.document_id, role="normative_body", normative=key != "informative")])
        await session.flush()
        unit = RetrievalUnit(version_id=version.version_id, unit_type="article", title="条款依据", text="来源正文", content_hash="b" * 64, status="verified")
        session.add(unit)
        await session.flush()
        for index in [1, 2]:
            node = ContentNode(parse_run_id=parse.parse_run_id, document_id=document.document_id, node_type="article", order_path=str(index), text="来源正文", content_hash="b" * 64)
            session.add(node)
            await session.flush()
            session.add(RetrievalUnitSource(unit_id=unit.unit_id, node_id=node.node_id, sequence=index))
        session.add_all([
            DecisionRule(rule_key=f"{key}-current", scenario="contract_change", source_kind="asset", asset_version_id=version.version_id, retrieval_unit_id=unit.unit_id, status="current"),
            DecisionRule(rule_key=f"{key}-pending", scenario="contract_change", source_kind="asset", asset_version_id=version.version_id, retrieval_unit_id=unit.unit_id, status="pending_review"),
        ])
    await session.commit()
    response = await _get(user, "/api/v1/dashboard/workbench")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["active_rules"] == data["pending_rule_reviews"] == 1
