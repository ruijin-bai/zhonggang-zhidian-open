"""Regulation & clause DTOs."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


class RegulationUploadRequest(BaseModel):
    regulation_code: str = ""
    title: str
    source: str = ""
    version: str = "v1"
    effective_date: str | None = None
    expiry_date: str | None = None
    replaces_file_id: str | None = None
    ingest_error: str | None = None
    owner_org: str | None = None
    org_path: str = "/"
    secret_level: str = "internal"
    domain: str = "*"
    lang: str = "zh"


class RegulationUploadResponse(BaseModel):
    file_id: str
    job_id: str | None = None
    status: str
    clause_count: int
    ingest_error: str | None = None


class AnnotationRequest(BaseModel):
    scenario_tags: list[str] = []
    secret_level: str | None = None
    permission_level: str | None = None


class RegulationReviewRequest(BaseModel):
    approved: bool
    note: str = ""


class RegulationMetadataUpdate(BaseModel):
    regulation_code: str | None = Field(default=None, max_length=128)
    effective_date: date | None = None
    expiry_date: date | None = None
    owner_org: str | None = Field(default=None, max_length=128)
    domain: str | None = Field(default=None, max_length=64)
    evidence_note: str = Field(min_length=2, max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.effective_date and self.expiry_date and self.expiry_date < self.effective_date:
            raise ValueError("失效日期不能早于生效日期")
        return self


class ClauseOut(BaseModel):
    clause_id: str
    file_id: str
    chapter: str | None = None
    clause_no: str = ""
    content: str
    permission_level: str | None = None
    secret_level: str
    scenario_tags: list = []
    status: str
    source_page: int | None = None
    source_locator: str | None = None
    content_hash: str | None = None
    heading_path: list[str] = []
    block_type: str = "paragraph"


class ClauseDetailOut(ClauseOut):
    source_kind: str = "regulation"
    document_title: str | None = None
    asset_version_id: str | None = None
    historical: bool = False
    snapshot_only: bool = False
    file_title: str = ""
    file_version: str = ""
    file_status: str = ""
    tags: list[str] = []


class RegulationOut(BaseModel):
    file_id: str
    regulation_code: str
    title: str
    source: str
    version: str
    status: str
    effective_date: str | None = None
    expiry_date: str | None = None
    replaces_file_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_note: str | None = None
    ingest_error: str | None = None
    has_original: bool = False
    has_ingestion_job: bool = False
    owner_org: str | None = None
    org_path: str = "/"
    secret_level: str
    domain: str
    lang: str
    tags: list[str] = []
    document_count: int = 0
    authority_verified: bool = False
    authority_gaps: list[str] = []
    source_verification: str = "unconfirmed"
    parse_backend: str = "legacy"
    parse_quality_score: int | None = None
    parse_quality_report: dict = {}


class RegulationGovernanceGap(BaseModel):
    file_id: str
    title: str
    status: str
    missing_fields: list[str] = []
    regulation_code: str | None = None
    effective_date: str | None = None
    owner_org: str | None = None
    domain: str = "*"


class RegulationDocumentOut(BaseModel):
    doc_id: str
    doc_type: str
    title: str
    filename: str
    mime: str
    object_key: str | None = None
