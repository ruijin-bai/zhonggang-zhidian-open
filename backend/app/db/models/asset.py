"""V2 compound governance-asset persistence model.

The V1 tables remain intact during migration. These tables separate logical
assets, releases, physical documents, immutable parse snapshots, source-faithful
content nodes and rebuildable retrieval units.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.db.base import Base, EmbeddingType, TimestampMixin, gen_id


class KnowledgeAsset(Base, TimestampMixin):
    __tablename__ = "knowledge_asset"
    __table_args__ = (
        Index("ix_knowledge_asset_visibility", "status", "secret_level", "org_path"),
    )

    asset_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("asset"))
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    business_code: Mapped[str] = mapped_column(String(96), nullable=False, default="", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_org: Mapped[str | None] = mapped_column(ForeignKey("org_unit.org_id"), nullable=True)
    org_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/")
    secret_level: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    domain: Mapped[str] = mapped_column(String(64), nullable=False, default="*")
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="zh")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    governance_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    versions: Mapped[list["AssetVersion"]] = relationship(
        "AssetVersion", back_populates="asset", cascade="all, delete-orphan"
    )


class ReleaseEvent(Base, TimestampMixin):
    __tablename__ = "release_event"

    release_event_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("release")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    issue_no: Mapped[str] = mapped_column(String(96), nullable=False, default="", index=True)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    release_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AssetVersion(Base, TimestampMixin):
    __tablename__ = "asset_version"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_label", name="uq_asset_version_label"),
        Index("ix_asset_version_effective_window", "release_state", "effective_date", "expiry_date"),
    )

    version_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("av")
    )
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_asset.asset_id"), nullable=False, index=True
    )
    release_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("release_event.release_event_id"), nullable=True, index=True
    )
    version_label: Mapped[str] = mapped_column(String(48), nullable=False, default="v1")
    release_state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    ingestion_state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    issue_no: Mapped[str] = mapped_column(String(96), nullable=False, default="", index=True)
    supersedes_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_version.version_id"), nullable=True, index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("user.user_id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legacy_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("regulation_file.file_id"), nullable=True, index=True
    )
    version_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    asset: Mapped["KnowledgeAsset"] = relationship("KnowledgeAsset", back_populates="versions")
    documents: Mapped[list["AssetVersionDocument"]] = relationship(
        "AssetVersionDocument", back_populates="version", cascade="all, delete-orphan"
    )


class AssetDocument(Base, TimestampMixin):
    __tablename__ = "asset_document"
    __table_args__ = (
        Index("ix_asset_document_hash", "sha256"),
        Index("ix_asset_document_disposition", "parse_disposition", "secret_level"),
    )

    document_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("adoc")
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    secret_level: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    parse_disposition: Mapped[str] = mapped_column(String(24), nullable=False, default="structured")
    disposition_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class AssetVersionDocument(Base, TimestampMixin):
    __tablename__ = "asset_version_document"
    __table_args__ = (
        UniqueConstraint("version_id", "document_id", name="uq_asset_version_document"),
        Index("ix_asset_version_document_order", "version_id", "role", "sort_order"),
    )

    link_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("avd"))
    version_id: Mapped[str] = mapped_column(
        ForeignKey("asset_version.version_id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("asset_document.document_id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    normative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relation_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    version: Mapped["AssetVersion"] = relationship("AssetVersion", back_populates="documents")
    document: Mapped["AssetDocument"] = relationship("AssetDocument")


class AssetRelationV2(Base, TimestampMixin):
    __tablename__ = "asset_relation_v2"
    __table_args__ = (
        UniqueConstraint(
            "from_version_id", "to_version_id", "relation_type", name="uq_asset_relation_v2"
        ),
    )

    relation_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("arel"))
    from_version_id: Mapped[str] = mapped_column(
        ForeignKey("asset_version.version_id"), nullable=False, index=True
    )
    to_version_id: Mapped[str] = mapped_column(
        ForeignKey("asset_version.version_id"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    note: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relation_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class DocumentRelation(Base, TimestampMixin):
    __tablename__ = "document_relation"
    __table_args__ = (
        UniqueConstraint(
            "from_document_id", "to_document_id", "relation_type", name="uq_document_relation"
        ),
    )

    relation_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("drel"))
    from_document_id: Mapped[str] = mapped_column(
        ForeignKey("asset_document.document_id"), nullable=False, index=True
    )
    to_document_id: Mapped[str] = mapped_column(
        ForeignKey("asset_document.document_id"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_node_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class DocumentParseRun(Base, TimestampMixin):
    __tablename__ = "document_parse_run"
    __table_args__ = (
        Index("ix_document_parse_run_current", "document_id", "is_current", "status"),
    )

    parse_run_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("parse")
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("asset_document.document_id"), nullable=False, index=True
    )
    parser_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False, default="1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    anchor_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    parser_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)


class ContentNode(Base, TimestampMixin):
    __tablename__ = "content_node"
    __table_args__ = (
        UniqueConstraint("parse_run_id", "order_path", name="uq_content_node_order_path"),
        Index("ix_content_node_document_order", "document_id", "order_path"),
        Index("ix_content_node_citable", "parse_run_id", "is_citable", "node_type"),
    )

    node_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("node"))
    parse_run_id: Mapped[str] = mapped_column(
        ForeignKey("document_parse_run.parse_run_id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("asset_document.document_id"), nullable=False, index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("content_node.node_id"), nullable=True, index=True
    )
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    order_path: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_locator: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source_bbox: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cell_range: Mapped[str | None] = mapped_column(String(64), nullable=True)
    structure: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_citable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class CitationSpan(Base, TimestampMixin):
    __tablename__ = "citation_span"
    __table_args__ = (
        Index("ix_citation_span_node", "node_id", "start_offset", "end_offset"),
    )

    span_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("span"))
    node_id: Mapped[str] = mapped_column(
        ForeignKey("content_node.node_id"), nullable=False, index=True
    )
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quote_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    locator: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RetrievalUnit(Base, TimestampMixin):
    __tablename__ = "retrieval_unit"
    __table_args__ = (
        Index("ix_retrieval_unit_gate", "status", "secret_level", "version_id"),
    )

    unit_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("unit"))
    version_id: Mapped[str] = mapped_column(
        ForeignKey("asset_version.version_id"), nullable=False, index=True
    )
    unit_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    secret_level: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate", index=True)
    unit_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class RetrievalUnitSource(Base, TimestampMixin):
    __tablename__ = "retrieval_unit_source"
    __table_args__ = (
        UniqueConstraint("unit_id", "node_id", "sequence", name="uq_retrieval_unit_source"),
    )

    source_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: gen_id("usrc"))
    unit_id: Mapped[str] = mapped_column(
        ForeignKey("retrieval_unit.unit_id"), nullable=False, index=True
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("content_node.node_id"), nullable=False, index=True)
    span_id: Mapped[str | None] = mapped_column(ForeignKey("citation_span.span_id"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class RetrievalEmbedding(Base, TimestampMixin):
    __tablename__ = "retrieval_embedding"
    __table_args__ = (
        UniqueConstraint("unit_id", "model_key", name="uq_retrieval_embedding_model"),
        Index("ix_retrieval_embedding_model_state", "status", "model_key", "unit_id"),
    )

    embedding_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("uemb")
    )
    unit_id: Mapped[str] = mapped_column(
        ForeignKey("retrieval_unit.unit_id"), nullable=False, index=True
    )
    model_key: Mapped[str] = mapped_column(String(128), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float] | None] = mapped_column(
        EmbeddingType(get_settings().EMBED_DIM), nullable=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)


class KnowledgeAssertion(Base, TimestampMixin):
    __tablename__ = "knowledge_assertion"
    __table_args__ = (
        Index("ix_knowledge_assertion_review", "version_id", "review_status", "assertion_type"),
    )

    assertion_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("fact")
    )
    version_id: Mapped[str] = mapped_column(
        ForeignKey("asset_version.version_id"), nullable=False, index=True
    )
    assertion_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    predicate: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    object_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    qualifiers: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate", index=True)
    extracted_by: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    assertion_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class AssertionEvidence(Base, TimestampMixin):
    __tablename__ = "assertion_evidence"
    __table_args__ = (
        UniqueConstraint("assertion_id", "span_id", name="uq_assertion_evidence"),
    )

    evidence_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("aevi")
    )
    assertion_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_assertion.assertion_id"), nullable=False, index=True
    )
    span_id: Mapped[str] = mapped_column(ForeignKey("citation_span.span_id"), nullable=False, index=True)
    evidence_role: Mapped[str] = mapped_column(String(24), nullable=False, default="support")


class LegacyAssetMapping(Base, TimestampMixin):
    __tablename__ = "legacy_asset_mapping"
    __table_args__ = (
        UniqueConstraint(
            "legacy_type", "legacy_id", "target_type", "target_id",
            name="uq_legacy_asset_mapping",
        ),
    )

    mapping_id: Mapped[str] = mapped_column(
        String(32), primary_key=True, default=lambda: gen_id("map")
    )
    legacy_type: Mapped[str] = mapped_column(String(32), nullable=False)
    legacy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mapping_status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    note: Mapped[str] = mapped_column(String(512), nullable=False, default="")
