"""Audit legacy parse quality and safely replace only defective, unlinked units.

Usage:
  python scripts/audit_reparse_library.py          # score only
  python scripts/audit_reparse_library.py --apply  # preserve old units as isolated audit evidence
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select, update

from app.adapters.storage.object_store import get_object_store
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.rule import DecisionRule
from app.db.session import SessionLocal
from app.services.eval.publish_gate import evaluate_publish_candidate
from app.services.ingestion.annotator import append_clauses_to_file
from app.services.ingestion.embed_job import embed_pending_clauses
from app.services.ingestion.parser import RawClause, extract_text
from app.services.ingestion.quality import assess_parse_quality
from app.services.ingestion.structured_parser import parse_document_structured


async def run(apply: bool) -> dict:
    stats = {"total": 0, "audited": 0, "reparsed": 0, "skipped_linked": 0, "unreadable": 0, "failed": 0, "issues": []}
    store = get_object_store()
    async with SessionLocal() as session:
        file_ids = list((await session.execute(select(RegulationFile.file_id))).scalars())
    stats["total"] = len(file_ids)
    for file_id in file_ids:
        async with SessionLocal() as session:
            regulation = await session.get(RegulationFile, file_id)
            if regulation is None:
                stats["unreadable"] += 1
                stats["issues"].append({"file_id": file_id, "reason": "missing_original"})
                continue
            title = regulation.title
            if not regulation.object_key:
                regulation.parse_backend = "legacy"
                regulation.parse_quality_score = 0
                regulation.parse_quality_report = {
                    "score": 0, "passed": False, "backend": "legacy", "clause_count": 0,
                    "source_chars": 0, "parsed_chars": 0, "coverage": 0,
                    "max_clause_chars": 0, "p95_clause_chars": 0, "anchored_ratio": 0,
                    "warnings": ["原始文件缺失，无法验证或重解析"],
                }
                await session.commit()
                stats["unreadable"] += 1
                stats["issues"].append({"file_id": file_id, "title": title, "reason": "missing_original"})
                continue
            source = store.get_object(regulation.object_key)
            if source is None:
                stats["unreadable"] += 1
                stats["issues"].append({"file_id": file_id, "title": title, "reason": "unreadable_original"})
                continue
            filename = Path(store._object_name(regulation.object_key)).name
            current = list((await session.execute(select(Clause).where(
                Clause.file_id == file_id, Clause.status == "current"
            ))).scalars())
            legacy = [RawClause(
                chapter=item.chapter, clause_no=item.clause_no, content=item.content,
                source_page=item.source_page, source_locator=item.source_locator,
                heading_path=item.heading_path or [], block_type=item.block_type,
            ) for item in current]
            try:
                source_text = extract_text(filename, source)
                old_report = assess_parse_quality(
                    source_text, legacy, backend=regulation.parse_backend or "legacy", filename=filename
                )
                regulation.parse_quality_score = old_report.score
                regulation.parse_quality_report = old_report.model_dump()
                stats["audited"] += 1
                if not apply or old_report.passed:
                    await session.commit()
                    continue
                linked = (await session.execute(select(DecisionRule.rule_id).where(
                    DecisionRule.clause_id.in_([item.clause_id for item in current])
                ).limit(1))).scalar_one_or_none() if current else None
                if linked:
                    report = old_report.model_dump()
                    report["warnings"] = [*report["warnings"], "存在已生效结构化规则，需先完成人工规则迁移"]
                    regulation.parse_quality_report = report
                    stats["skipped_linked"] += 1
                    stats["issues"].append({"file_id": file_id, "title": title, "reason": "linked_rule"})
                    await session.commit()
                    continue
                candidate, new_report = await parse_document_structured(filename, source)
                if not new_report.passed or new_report.score <= old_report.score:
                    stats["failed"] += 1
                    stats["issues"].append({
                        "file_id": file_id, "title": title, "reason": "candidate_not_better",
                        "old_score": old_report.score, "new_score": new_report.score,
                        "warnings": new_report.warnings,
                    })
                    await session.commit()
                    continue
                old_ids = [item.clause_id for item in current]
                if old_ids:
                    await session.execute(update(Clause).where(Clause.clause_id.in_(old_ids)).values(status="isolated"))
                await append_clauses_to_file(session, file_id, candidate, secret_level=regulation.secret_level)
                regulation.parse_backend = new_report.backend
                regulation.parse_quality_score = new_report.score
                regulation.parse_quality_report = new_report.model_dump()
                await embed_pending_clauses(session)
                readiness = await evaluate_publish_candidate(session, regulation)
                if not readiness["passed"]:
                    stats["failed"] += 1
                    stats["issues"].append({
                        "file_id": file_id, "title": title,
                        "reason": "retrieval_gate", "detail": readiness["reason"],
                        "checks": readiness.get("checks", []),
                    })
                    await session.rollback()
                    continue
                await session.commit()
                stats["reparsed"] += 1
            except Exception:  # noqa: BLE001 - continue auditing the remaining corpus
                await session.rollback()
                stats["failed"] += 1
                stats["issues"].append({"file_id": file_id, "title": title, "reason": "exception"})
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(asyncio.run(run(args.apply)))
