"""Explicit, permission-bound rule evidence across both persisted source models."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import and_, or_, select

from app.db.models.asset import AssetDocument, AssetVersion, AssetVersionDocument, ContentNode, DocumentParseRun, KnowledgeAsset, RetrievalUnit, RetrievalUnitSource
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.services.assets.retrieval_index import eligible_unit_predicates
from app.services.governance_state import is_authority_verified
from app.services.assets.publication import source_verification as asset_verification
from app.services.permission.rbac import build_asset_filter, build_filter


@dataclass(frozen=True)
class SourceClause:
    clause_id: str
    file_id: str
    clause_no: str
    content: str
    status: str
    source_page: int | None
    source_locator: str | None
    content_hash: str | None


@dataclass(frozen=True)
class SourceFile:
    file_id: str
    title: str
    version: str
    status: str
    effective_date: date | None
    expiry_date: date | None
    regulation_code: str
    owner_org: str | None
    domain: str
    source_kind: str = "asset"
    source_confirmation: dict = field(default_factory=dict)
    source_version_id: str | None = None


def asset_authority_gaps(asset, version) -> list[str]:
    if asset_verification(asset, version) == "maintainer":
        return []
    gaps = []
    if not (version.issue_no or "").strip() or version.issue_no.strip() == asset.title.strip():
        gaps.append("issue_no")
    if version.effective_date is None:
        gaps.append("effective_date")
    if not asset.owner_org:
        gaps.append("owner_org")
    if not asset.domain or asset.domain == "*":
        gaps.append("domain")
    return gaps


def legacy_effective_filter(today):
    return and_(RegulationFile.status == "current", or_(RegulationFile.effective_date.is_(None), RegulationFile.effective_date <= today), or_(RegulationFile.expiry_date.is_(None), RegulationFile.expiry_date >= today))


def asset_source_statement(user, permissions, *, effective: bool = False, today: date | None = None):
    stmt = (select(RetrievalUnit, AssetVersion, KnowledgeAsset, AssetDocument, ContentNode, AssetVersionDocument)
        .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
        .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
        .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
        .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
        .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
        .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
        .join(AssetVersionDocument, (AssetVersionDocument.version_id == AssetVersion.version_id) & (AssetVersionDocument.document_id == AssetDocument.document_id))
        .where(build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level, org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain, content_secret_level=RetrievalUnit.secret_level), build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level, org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain, content_secret_level=AssetDocument.secret_level)))
    if effective:
        stmt = stmt.where(*eligible_unit_predicates(today), AssetVersionDocument.normative.is_(True))
    return stmt


def normalise_asset_source(row):
    unit, version, asset, document, node, _link = row[:6]
    clause = SourceClause(unit.unit_id, asset.asset_id, (unit.title or node.label or node.source_locator or "正文")[:64], unit.text, unit.status, node.source_page, node.source_locator, unit.content_hash)
    file = SourceFile(asset.asset_id, asset.title, version.version_label, version.release_state, version.effective_date, version.expiry_date, version.issue_no, asset.owner_org, asset.domain,
        source_confirmation=(version.version_metadata or {}).get("source_confirmation", {}) if asset_verification(asset, version) == "maintainer" else {}, source_version_id=version.version_id)
    return clause, file


async def source_for_create(db, body, user, permissions):
    if body.source_kind == "asset":
        row = (await db.execute(asset_source_statement(user, permissions, effective=True).where(RetrievalUnit.unit_id == body.retrieval_unit_id, AssetVersion.version_id == body.asset_version_id))).first()
        if row is None or asset_authority_gaps(row[2], row[1]):
            return None
        return normalise_asset_source(row)
    return (await db.execute(select(Clause, RegulationFile).join(RegulationFile, Clause.file_id == RegulationFile.file_id).where(Clause.clause_id == body.clause_id, Clause.file_id == body.file_id, Clause.status == "current", legacy_effective_filter(date.today()), build_filter(user, permissions, Clause.secret_level)))).first()


async def load_rule_sources(db, user, permissions, *, statuses=None, scenario=None, rule_id=None, effective=False, require_authority=False, as_of=None):
    today = as_of or date.today()
    legacy = select(DecisionRule, Clause, RegulationFile).join(Clause, DecisionRule.clause_id == Clause.clause_id).join(RegulationFile, DecisionRule.file_id == RegulationFile.file_id).where(DecisionRule.source_kind == "regulation", build_filter(user, permissions, Clause.secret_level))
    compound = asset_source_statement(user, permissions, effective=effective, today=today).add_columns(DecisionRule).join(DecisionRule, (DecisionRule.retrieval_unit_id == RetrievalUnit.unit_id) & (DecisionRule.asset_version_id == AssetVersion.version_id)).where(DecisionRule.source_kind == "asset")
    if effective:
        legacy = legacy.where(Clause.status == "current", legacy_effective_filter(today))
    for field, value in ((DecisionRule.scenario, scenario), (DecisionRule.rule_id, rule_id)):
        if value is not None:
            legacy = legacy.where(field == value); compound = compound.where(field == value)
    if statuses:
        legacy = legacy.where(DecisionRule.status.in_(statuses)); compound = compound.where(DecisionRule.status.in_(statuses))
    result = [row for row in (await db.execute(legacy)).all() if not require_authority or is_authority_verified(row[2])]
    seen = set()
    for row in (await db.execute(compound)).all():
        rule = row[6]
        if rule.rule_id in seen or (require_authority and asset_authority_gaps(row[2], row[1])):
            continue
        seen.add(rule.rule_id)
        clause, file = normalise_asset_source(row)
        result.append((rule, clause, file))
    result.sort(key=lambda row: (row[0].priority, row[0].created_at.isoformat() if row[0].created_at else "", row[0].rule_id))
    return result
