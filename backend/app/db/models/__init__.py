"""Model package — importing it registers every ORM class on ``Base.metadata``.

Required so that ``Base.metadata.create_all`` / Alembic autogenerate see all
tables regardless of which service imported first.
"""
from app.db.models.org import OrgUnit
from app.db.models.regulation import RegulationFile
from app.db.models.regulation_document import RegulationDocument
from app.db.models.clause import Clause
from app.db.models.tag import Tag, clause_tag, regulation_tag
from app.db.models.relation import Relation
from app.db.models.user import User
from app.db.models.permission import Permission
from app.db.models.push import PushRecord, PushReceipt, PushSubscription
from app.db.models.qa import QASession, QACitation
from app.db.models.feedback import QAFeedback
from app.db.models.eval import TestCase, TestRun
from app.db.models.audit import AuditLog
from app.db.models.model_config import ModelConfig
from app.db.models.ingestion import IngestionJob
from app.db.models.rule import DecisionRule
from app.db.models.business_case import BusinessCase
from app.db.models.impact import ChangeImpactRun, ChangeImpactItem
from app.db.models.governance_task import GovernanceTask
from app.db.models.trial import TrialBenchmarkRecord, TrialUsageEvent
from app.db.models.asset import (
    KnowledgeAsset,
    ReleaseEvent,
    AssetVersion,
    AssetDocument,
    AssetVersionDocument,
    AssetRelationV2,
    DocumentRelation,
    DocumentParseRun,
    ContentNode,
    CitationSpan,
    RetrievalUnit,
    RetrievalUnitSource,
    RetrievalEmbedding,
    KnowledgeAssertion,
    AssertionEvidence,
    LegacyAssetMapping,
)

__all__ = [
    "OrgUnit",
    "RegulationFile",
    "RegulationDocument",
    "Clause",
    "Tag",
    "clause_tag",
    "regulation_tag",
    "Relation",
    "User",
    "Permission",
    "PushRecord",
    "PushReceipt",
    "PushSubscription",
    "QASession",
    "QACitation",
    "QAFeedback",
    "TestCase",
    "TestRun",
    "AuditLog",
    "ModelConfig",
    "IngestionJob",
    "DecisionRule",
    "BusinessCase",
    "ChangeImpactRun",
    "ChangeImpactItem",
    "GovernanceTask",
    "TrialUsageEvent",
    "TrialBenchmarkRecord",
    "KnowledgeAsset",
    "ReleaseEvent",
    "AssetVersion",
    "AssetDocument",
    "AssetVersionDocument",
    "AssetRelationV2",
    "DocumentRelation",
    "DocumentParseRun",
    "ContentNode",
    "CitationSpan",
    "RetrievalUnit",
    "RetrievalUnitSource",
    "RetrievalEmbedding",
    "KnowledgeAssertion",
    "AssertionEvidence",
    "LegacyAssetMapping",
]
