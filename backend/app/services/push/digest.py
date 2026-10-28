"""Change digest generation for update pushes (T13)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.clause import Clause
from app.db.models.relation import Relation
from app.db.models.regulation import RegulationFile


async def generate_digest(session: AsyncSession, new_file_id: str, old_file_id: str | None = None) -> str:
    new_file = await session.get(RegulationFile, new_file_id)
    if new_file is None:
        return "（制度文件不存在）"

    new_clauses = list((await session.execute(select(Clause).where(Clause.file_id == new_file_id))).scalars().all())
    new_tags = []
    for c in new_clauses:
        for t in c.scenario_tags or []:
            if t not in new_tags:
                new_tags.append(t)

    lines = [
        f"制度《{new_file.title}》更新至版本 {new_file.version}。",
        f"本次纳入条款 {len(new_clauses)} 条；涉及业务场景：{('、'.join(new_tags) if new_tags else '—')}。",
    ]

    if old_file_id:
        old_file = await session.get(RegulationFile, old_file_id)
        old_clauses = list((await session.execute(select(Clause).where(Clause.file_id == old_file_id))).scalars().all())
        lines.append(f"相较上一版本《{old_file.title if old_file else '?'}》（{old_file.version if old_file else '?'}），"
                     f"条款数由 {len(old_clauses)} 变为 {len(new_clauses)}。")

    # Conflict relations touching this file.
    rels = list(
        (
            await session.execute(
                select(Relation).where(
                    (Relation.from_id == new_file_id) | (Relation.to_id == new_file_id),
                    Relation.rel_type == "conflict",
                )
            )
        ).scalars().all()
    )
    if rels:
        lines.append("⚠ 存在跨制度冲突关系，执行时以新版或上级制度为准；详见关系图谱。")

    return "\n".join(lines)
