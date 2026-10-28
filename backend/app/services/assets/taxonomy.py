"""Controlled vocabularies for the compound governance-asset model.

Values are persisted as stable English keys. Chinese labels are presentation
metadata only, so wording improvements do not require data migrations.
"""
from __future__ import annotations

from enum import Enum


class LabeledEnum(str, Enum):
    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]


class AssetType(LabeledEnum):
    REGULATION = "regulation"
    MANAGEMENT_METHOD = "management_method"
    IMPLEMENTATION_RULE = "implementation_rule"
    GUIDELINE = "guideline"
    MANUAL = "manual"
    STANDARD = "standard"
    CHECKLIST = "checklist"
    TEMPLATE_PACKAGE = "template_package"
    COMPILATION = "compilation"
    RESOURCE_PACKAGE = "resource_package"
    KNOWLEDGE_MATERIAL = "knowledge_material"


ASSET_TYPE_LABELS = {
    AssetType.REGULATION.value: "规定制度",
    AssetType.MANAGEMENT_METHOD.value: "管理办法",
    AssetType.IMPLEMENTATION_RULE.value: "实施细则",
    AssetType.GUIDELINE.value: "业务指引",
    AssetType.MANUAL.value: "管理手册",
    AssetType.STANDARD.value: "标准规范",
    AssetType.CHECKLIST.value: "清单目录",
    AssetType.TEMPLATE_PACKAGE.value: "模板表单包",
    AssetType.COMPILATION.value: "制度汇编",
    AssetType.RESOURCE_PACKAGE.value: "资源资产包",
    AssetType.KNOWLEDGE_MATERIAL.value: "解读培训材料",
}


class DocumentRole(LabeledEnum):
    ISSUANCE_NOTICE = "issuance_notice"
    NORMATIVE_BODY = "normative_body"
    NORMATIVE_ANNEX = "normative_annex"
    STANDARD_TABLE = "standard_table"
    FLOWCHART = "flowchart"
    FORM = "form"
    TEMPLATE = "template"
    IMPLEMENTATION_GUIDE = "implementation_guide"
    DRAFTING_NOTE = "drafting_note"
    REVIEW_OPINION = "review_opinion"
    TRAINING = "training"
    HISTORY = "history"
    RAW_ASSET = "raw_asset"
    REFERENCE = "reference"


DOCUMENT_ROLE_LABELS = {
    DocumentRole.ISSUANCE_NOTICE.value: "印发通知",
    DocumentRole.NORMATIVE_BODY.value: "规范正文",
    DocumentRole.NORMATIVE_ANNEX.value: "规范性附件",
    DocumentRole.STANDARD_TABLE.value: "标准数据表",
    DocumentRole.FLOWCHART.value: "流程图",
    DocumentRole.FORM.value: "业务表单",
    DocumentRole.TEMPLATE.value: "工作模板",
    DocumentRole.IMPLEMENTATION_GUIDE.value: "实施说明",
    DocumentRole.DRAFTING_NOTE.value: "编制说明",
    DocumentRole.REVIEW_OPINION.value: "会审意见",
    DocumentRole.TRAINING.value: "宣贯培训",
    DocumentRole.HISTORY.value: "历史版本",
    DocumentRole.RAW_ASSET.value: "原始素材",
    DocumentRole.REFERENCE.value: "参考资料",
}


class AssetRelationType(LabeledEnum):
    ISSUES = "issues"
    ANNEX_OF = "annex_of"
    EXPLAINS = "explains"
    IMPLEMENTS = "implements"
    TEMPLATE_FOR = "template_for"
    SUPERSEDES = "supersedes"
    REFERENCES = "references"
    CONTAINS = "contains"
    DERIVED_FROM = "derived_from"
    SAME_RELEASE = "same_release"


class ContentNodeType(LabeledEnum):
    DOCUMENT = "document"
    PART = "part"
    CHAPTER = "chapter"
    SECTION = "section"
    ARTICLE = "article"
    PARAGRAPH = "paragraph"
    ITEM = "item"
    TABLE = "table"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    FORM = "form"
    FORM_FIELD = "form_field"
    FLOWCHART = "flowchart"
    FLOW_STEP = "flow_step"
    IMAGE = "image"
    CAPTION = "caption"
    SHEET = "sheet"
    SLIDE = "slide"
    OTHER = "other"


class ParseDisposition(LabeledEnum):
    STRUCTURED = "structured"
    METADATA_ONLY = "metadata_only"
    EXCLUDED = "excluded"


class ParseRunStatus(LabeledEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    NEEDS_REVIEW = "needs_review"
    REQUIRES_OCR = "requires_ocr"
    FAILED = "failed"


class ReviewStatus(LabeledEnum):
    CANDIDATE = "candidate"
    VERIFIED = "verified"
    REJECTED = "rejected"


def taxonomy_payload() -> dict[str, list[dict[str, str]]]:
    return {
        "asset_types": [
            {"value": item.value, "label": ASSET_TYPE_LABELS[item.value]} for item in AssetType
        ],
        "document_roles": [
            {"value": item.value, "label": DOCUMENT_ROLE_LABELS[item.value]}
            for item in DocumentRole
        ],
        "relation_types": [{"value": item.value, "label": item.value} for item in AssetRelationType],
        "node_types": [{"value": item.value, "label": item.value} for item in ContentNodeType],
        "parse_dispositions": [
            {"value": item.value, "label": item.value} for item in ParseDisposition
        ],
    }
