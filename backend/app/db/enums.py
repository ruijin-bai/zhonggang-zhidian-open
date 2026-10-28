"""Shared enumerations used across ORM models and services.

Secret levels carry an explicit rank so the RBAC filter can compare
``user_clearance >= resource_secret_level``.
"""
from __future__ import annotations

from enum import Enum


class OrgType(str, Enum):
    HEADQUARTER = "headquarter"  # 总部
    REGION = "region"  # 区域公司
    OVERSEAS = "overseas"  # 驻外机构

    @classmethod
    def label(cls, value: str) -> str:
        return {
            cls.HEADQUARTER.value: "总部",
            cls.REGION.value: "区域公司",
            cls.OVERSEAS.value: "驻外机构",
        }.get(value, value)


class RegulationStatus(str, Enum):
    PROCESSING = "processing"  # 解析中（异步入库进行中）
    PENDING_REVIEW = "pending_review"  # 解析与发布门禁已通过，待业务审核
    CURRENT = "current"  # 现行
    FAILED = "failed"  # 解析失败
    REJECTED = "rejected"  # 审核驳回，未对员工发布
    REPEALED = "repealed"  # 废止
    REPLACED = "replaced"  # 替代


class ClauseStatus(str, Enum):
    CURRENT = "current"
    ISOLATED = "isolated"  # 失效版本隔离，不参与召回


class RelationType(str, Enum):
    REPLACE = "replace"  # 替代
    SUBORDINATE = "subordinate"  # 从属
    MULTI_CONSTRAINT = "multi_constraint"  # 多制度约束
    CONFLICT = "conflict"  # 冲突

    @classmethod
    def label(cls, value: str) -> str:
        return {
            cls.REPLACE.value: "替代",
            cls.SUBORDINATE.value: "从属",
            cls.MULTI_CONSTRAINT.value: "多制度约束",
            cls.CONFLICT.value: "冲突",
        }.get(value, value)


class Role(str, Enum):
    R1 = "R1"  # 普通员工 / 驻外人员
    R2 = "R2"  # 职能审核骨干
    R3 = "R3"  # 知识库管理员
    R4 = "R4"  # 系统管理员


class SecretLevel(str, Enum):
    PUBLIC = "public"  # 公开
    INTERNAL = "internal"  # 内部
    CONFIDENTIAL = "confidential"  # 机密
    SECRET = "secret"  # 绝密

    @classmethod
    def rank(cls, value: str) -> int:
        order = [cls.PUBLIC.value, cls.INTERNAL.value, cls.CONFIDENTIAL.value, cls.SECRET.value]
        try:
            return order.index(value)
        except ValueError:
            return 0


class PushStatus(str, Enum):
    DRAFT = "draft"  # 草稿
    PENDING_REVIEW = "pending_review"  # 待审核
    SENT = "sent"  # 已发
    RECALLED = "recalled"  # 已撤回


class ReadStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"


class FeedbackType(str, Enum):
    FAVORITE = "favorite"  # 收藏
    LIKE = "like"  # 点赞
    CORRECT = "correct"  # 纠错


class TestStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TestRunStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class DecisionRuleStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    CURRENT = "current"
    REJECTED = "rejected"
    RETIRED = "retired"


class BusinessCaseStatus(str, Enum):
    DRAFT = "draft"
    ASSESSED = "assessed"
    REVIEW_REQUIRED = "review_required"
    CONFIRMED = "confirmed"
    RETURNED = "returned"
