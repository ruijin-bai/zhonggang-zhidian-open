"""Seed script (T-基础设施 / 演示数据).

All organizations, regulations, amounts and approval paths below are synthetic;
they are not official policies of any organization.

Injects a coherent demo dataset so the full vertical chain works out of the box:
org units, R1–R4 users + RBAC permissions, regulation files with clauses
(embedded via the mock adapter), tags, cross-file relations, eval test cases and
a sample push. Idempotent: exits early if users already exist.

Usage:
    cd backend
    python -m scripts.seed
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base, gen_id
from app.db.enums import (
    OrgType,
    PushStatus,
    ReadStatus,
    RelationType,
    Role,
    SecretLevel,
)
from app.db.models.clause import Clause
from app.db.models.org import OrgUnit
from app.db.models.permission import Permission
from app.db.models.push import PushReceipt, PushRecord
from app.db.models.regulation import RegulationFile
from app.db.models.relation import Relation
from app.db.models.user import User
from app.db.session import SessionLocal, engine
from app.services.ingestion.annotator import create_regulation_with_clauses
from app.services.ingestion.embed_job import embed_pending_clauses

SETTINGS = get_settings()
DEFAULT_PASSWORD = os.getenv("SEED_DEFAULT_PASSWORD", "").strip()


async def _create_tables() -> None:
    # On SQLite (local dev) the Postgres-only `vector` extension is unavailable;
    # skip it and just create the tables so the stack boots without Postgres.
    if get_settings().is_sqlite:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return
    async with engine.begin() as conn:
        try:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:  # noqa: BLE001 - already exists
            pass
        await conn.run_sync(Base.metadata.create_all)


def _mk_org(session, org_id, parent_id, name, org_type, path):
    org = OrgUnit(org_id=org_id, parent_id=parent_id, name=name, org_type=org_type.value, path=path)
    session.add(org)
    return org


async def seed_all() -> None:
    if not DEFAULT_PASSWORD:
        raise RuntimeError("缺少 SEED_DEFAULT_PASSWORD；禁止使用仓库内置通用密码注入账号")
    await _create_tables()
    async with SessionLocal() as session:
        existing = (await session.execute(select(User))).scalars().first()
        if existing is not None:
            print("[seed] 数据已存在，跳过。")
            return

        # ---- Org units ----
        _mk_org(session, "org_hq", None, "示例企业总部", OrgType.HEADQUARTER, "/hq")
        _mk_org(session, "org_region1", "org_hq", "示例区域公司", OrgType.REGION, "/hq/region1")
        _mk_org(session, "org_ovs1", "org_region1", "驻外机构A（试点）", OrgType.OVERSEAS, "/hq/region1/overseas1")
        _mk_org(session, "org_ovs2", "org_region1", "驻外机构B", OrgType.OVERSEAS, "/hq/region1/overseas2")
        await session.flush()

        # ---- Users R1-R4 ----
        users = {
            "R1": User(user_id="user_r1", username="employee", hashed_password=hash_password(DEFAULT_PASSWORD),
                      org_id="org_ovs1", post="驻外业务岗", role=Role.R1.value, secret_clearance=SecretLevel.INTERNAL.value),
            "R2": User(user_id="user_r2", username="reviewer", hashed_password=hash_password(DEFAULT_PASSWORD),
                      org_id="org_hq", post="合规骨干", role=Role.R2.value, secret_clearance=SecretLevel.CONFIDENTIAL.value),
            "R3": User(user_id="user_r3", username="kbadmin", hashed_password=hash_password(DEFAULT_PASSWORD),
                      org_id="org_hq", post="知识库管理员", role=Role.R3.value, secret_clearance=SecretLevel.SECRET.value),
            "R4": User(user_id="user_r4", username="admin", hashed_password=hash_password(DEFAULT_PASSWORD),
                      org_id="org_hq", post="系统管理员", role=Role.R4.value, secret_clearance=SecretLevel.SECRET.value),
        }
        for u in users.values():
            session.add(u)
        await session.flush()

        # ---- RBAC permissions ----
        perms = [
            Permission(perm_id=gen_id("perm"), role=Role.R1.value, org_scope="/hq/region1/overseas1",
                       secret_level=SecretLevel.INTERNAL.value, domain="*"),
            Permission(perm_id=gen_id("perm"), role=Role.R2.value, org_scope="/",
                       secret_level=SecretLevel.CONFIDENTIAL.value, domain="*"),
            Permission(perm_id=gen_id("perm"), role=Role.R3.value, org_scope="/",
                       secret_level=SecretLevel.SECRET.value, domain="*"),
            Permission(perm_id=gen_id("perm"), role=Role.R4.value, org_scope="/",
                       secret_level=SecretLevel.SECRET.value, domain="*"),
        ]
        session.add_all(perms)
        await session.flush()

        # ---- Regulation 1: 境外项目管理办法 (drives the demo question) ----
        reg1 = await create_regulation_with_clauses(
            session,
            title="境外项目管理办法",
            source="制度库/境外业务",
            version="v2",
            owner_org="org_ovs1",
            org_path="/hq/region1/overseas1",
            secret_level=SecretLevel.INTERNAL.value,
            domain="境外项目",
            lang="zh",
            object_key=None,
            clauses=[
                type("C", (), {"chapter": "第二章 变更管理", "clause_no": "第12条",
                               "content": "境外项目变更款审批：单笔变更款超过50万美元的，须报区域总经理审核后报总部审批；"
                                          "10万至50万美元由区域总经理审批；10万美元以下由项目部审批。"})(),
                type("C", (), {"chapter": "第二章 变更管理", "clause_no": "第13条",
                               "content": "变更款申请须提交：变更申请函、原合同及变更依据、费用测算表、合规审查意见。"})(),
                type("C", (), {"chapter": "第三章 材料", "clause_no": "第21条",
                               "content": "境外项目付款材料应包括：发票、报关单、验收单及税务证明，材料不齐全不予拨付。"})(),
            ],
        )

        # ---- Regulation 2: 审批权限表（2026） ----
        reg2 = await create_regulation_with_clauses(
            session,
            title="审批权限表（2026）",
            source="制度库/权限",
            version="v1",
            owner_org="org_hq",
            org_path="/hq",
            secret_level=SecretLevel.INTERNAL.value,
            domain="*",
            lang="zh",
            object_key=None,
            clauses=[
                type("C", (), {"chapter": "总则", "clause_no": "第5条",
                               "content": "审批权限层级：项目部→区域总经理→总部。涉及境外业务的重大变更款须逐级上报总部审批。"})(),
            ],
        )

        # ---- Regulation 3: 差旅费管理办法 (used for push demo) ----
        reg3 = await create_regulation_with_clauses(
            session,
            title="差旅费管理办法",
            source="制度库/财务",
            version="v3",
            owner_org="org_hq",
            org_path="/hq",
            secret_level=SecretLevel.INTERNAL.value,
            domain="差旅",
            lang="zh",
            object_key=None,
            clauses=[
                type("C", (), {"chapter": "住宿", "clause_no": "第8条",
                               "content": "境内差旅住宿标准：一线城市不超过500元/天，其他城市不超过350元/天；境外按驻外标准执行。"})(),
                type("C", (), {"chapter": "报销", "clause_no": "第15条",
                               "content": "差旅费报销须提交：出差审批单、交通票据、住宿发票及出差报告。"})(),
            ],
        )

        # ---- Regulation 4: 驻外补充规定（试点） (from subordinate to 差旅费管理办法) ----
        reg4 = await create_regulation_with_clauses(
            session,
            title="驻外补充规定（试点）",
            source="制度库/驻外",
            version="v1",
            owner_org="org_ovs1",
            org_path="/hq/region1/overseas1",
            secret_level=SecretLevel.INTERNAL.value,
            domain="差旅",
            lang="zh",
            object_key=None,
            clauses=[
                type("C", (), {"chapter": "差旅", "clause_no": "第3条",
                               "content": "驻外人员差旅住宿在总部标准基础上上浮30%，其余按《差旅费管理办法》执行。"})(),
            ],
        )

        # ---- Regulation 5: 内部审计规定 (CONFIDENTIAL — R1 must NOT see) ----
        reg5 = await create_regulation_with_clauses(
            session,
            title="内部审计工作规定",
            source="制度库/审计",
            version="v1",
            owner_org="org_hq",
            org_path="/hq",
            secret_level=SecretLevel.CONFIDENTIAL.value,
            domain="*",
            lang="zh",
            object_key=None,
            clauses=[
                type("C", (), {"chapter": "审计权限", "clause_no": "第4条",
                               "content": "内部审计组有权调阅全部境外项目财务资料，被审计单位应予配合。"})(),
            ],
        )

        await session.flush()

        # ---- Cross-file relations ----
        session.add(Relation(from_id=reg4.file_id, to_id=reg3.file_id, rel_type=RelationType.SUBORDINATE.value,
                             note="驻外补充规定从属于《差旅费管理办法》", confirmed_by="user_r2"))
        session.add(Relation(from_id=reg1.file_id, to_id=reg2.file_id, rel_type=RelationType.MULTI_CONSTRAINT.value,
                             note="变更款审批受《审批权限表》多重约束", confirmed_by="user_r2"))
        await session.flush()

        # ---- Embeddings ----
        n = await embed_pending_clauses(session)
        print(f"[seed] 已向量化条款 {n} 条")

        # ---- Eval test cases ----
        # Resolve the 变更款 clause id for the expected set.
        c12 = (await session.execute(
            select(Clause).where(Clause.file_id == reg1.file_id, Clause.clause_no == "第12条")
        )).scalar_one_or_none()
        c5 = (await session.execute(
            select(Clause).where(Clause.file_id == reg2.file_id, Clause.clause_no == "第5条")
        )).scalar_one_or_none()
        expected = [c.clause_id for c in (c12, c5) if c]
        from app.db.models.eval import TestCase as TCModel
        session.add(TCModel(
            case_id=gen_id("case"),
            question="境外项目变更款50万美元由谁审批？",
            expected_clause_ids=expected,
            standard_answer="单笔超过50万美元须报区域总经理审核后报总部审批。",
            scenario_tag="变更款审批",
            created_by="user_r3",
            status="active",
        ))
        session.add(TCModel(
            case_id=gen_id("case"),
            question="差旅费报销需要提交哪些材料？",
            expected_clause_ids=[c.clause_id for c in (
                (await session.execute(select(Clause).where(Clause.file_id == reg3.file_id, Clause.clause_no == "第15条"))).scalar_one_or_none(),
            ) if c],
            standard_answer="出差审批单、交通票据、住宿发票及出差报告。",
            scenario_tag="差旅",
            created_by="user_r3",
            status="active",
        ))
        await session.flush()

        # ---- Sample push (差旅费管理办法 v3 修订已发布) ----
        push = PushRecord(
            file_id=reg3.file_id,
            target_role=Role.R1.value,
            scenario_tag="差旅",
            status=PushStatus.SENT.value,
            digest="《差旅费管理办法》更新至 v3：住宿标准上调，报销材料要求细化。",
            created_by="user_r3",
        )
        session.add(push)
        await session.flush()
        for uid in ("user_r1", "user_r2"):
            session.add(PushReceipt(push_id=push.push_id, user_id=uid, read_status=ReadStatus.UNREAD.value))

        await session.commit()
        print("[seed] 完成：组织4个、用户4个、制度5个、关系2条、测试用例2条、推送1条。")


if __name__ == "__main__":
    asyncio.run(seed_all())
