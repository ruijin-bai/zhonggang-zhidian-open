"""Build and optionally parse the V2 compound-asset benchmark corpus.

Examples:
  python -m scripts.migrate_compound_assets
  python -m scripts.migrate_compound_assets --apply
  python -m scripts.migrate_compound_assets --apply --parse

The command is idempotent and never deletes or updates V1 regulation/clause
records. Reports contain titles and counts only, never document body text.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import func, select

from app.db.models.asset import AssetVersionDocument, DocumentParseRun, LegacyAssetMapping
from app.db.models.regulation import RegulationFile
from app.db.models.regulation_document import RegulationDocument
from app.db.session import SessionLocal, engine
from app.services.assets.benchmark_manifest import BENCHMARK_TITLES
from app.services.assets.migration import migrate_legacy_regulation
from app.services.assets.parse_service import parse_asset_document
from app.services.model_runtime import load_runtime_model_config


async def run(
    apply: bool,
    parse: bool,
    title: str | None = None,
    document_id: str | None = None,
    current_status: str | None = None,
    all_current: bool = False,
) -> dict:
    if document_id:
        async with SessionLocal() as session:
            try:
                result = await parse_asset_document(session, document_id)
                await session.commit()
                return {"apply": True, "parse": True, "document": result}
            except Exception as exc:  # noqa: BLE001 - persist first-parse failure evidence
                await session.commit()
                return {
                    "apply": True,
                    "parse": True,
                    "document": {"document_id": document_id, "status": "failed", "error": str(exc)[:200]},
                }
    if current_status:
        async with SessionLocal() as session:
            document_ids = list((await session.execute(
                select(DocumentParseRun.document_id).where(
                    DocumentParseRun.is_current.is_(True),
                    DocumentParseRun.status == current_status,
                )
            )).scalars())
            results = []
            for target_id in document_ids:
                try:
                    results.append(await parse_asset_document(session, target_id))
                    await session.commit()
                except Exception as exc:  # noqa: BLE001 - preserve independent checkpoints
                    await session.commit()
                    results.append({
                        "document_id": target_id,
                        "status": "failed",
                        "error": str(exc)[:200],
                    })
            counts: dict[str, int] = {}
            for item in results:
                status = item["status"]
                counts[status] = counts.get(status, 0) + 1
            return {
                "apply": True,
                "parse": True,
                "selected_current_status": current_status,
                "document_count": len(document_ids),
                "parse_counts": counts,
                "documents": results,
            }
    requested = [title] if title else BENCHMARK_TITLES
    async with SessionLocal() as session:
        source_stmt = select(RegulationFile)
        if all_current:
            source_stmt = source_stmt.where(RegulationFile.status == "current")
        else:
            source_stmt = source_stmt.where(RegulationFile.title.in_(requested))
        rows = list((await session.execute(source_stmt.order_by(RegulationFile.title))).scalars())
        if all_current:
            requested = [row.title for row in rows]
        found = {row.title for row in rows}
        preview = []
        for row in rows:
            document_count = int((await session.execute(
                select(func.count()).select_from(RegulationDocument).where(
                    RegulationDocument.file_id == row.file_id
                )
            )).scalar_one())
            preview.append({
                "title": row.title,
                "file_id": row.file_id,
                "document_count": document_count,
            })
        result = {
            "apply": apply,
            "parse": parse,
            "requested": len(requested),
            "found": len(rows),
            "missing": [item for item in requested if item not in found],
            "assets": preview,
            "version_count": 0,
            "document_count": 0,
            "parse_counts": {},
            "issues": [],
        }
        if not apply:
            return result

        version_ids: list[str] = []
        for row in rows:
            try:
                version_ids.extend(await migrate_legacy_regulation(session, row.file_id))
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - preserve completed asset packages
                await session.rollback()
                result["issues"].append({"title": row.title, "stage": "migrate", "error": str(exc)[:200]})
        result["version_count"] = len(version_ids)

        if not version_ids:
            version_ids = list((await session.execute(
                select(LegacyAssetMapping.target_id).where(
                    LegacyAssetMapping.legacy_type == "regulation_file",
                    LegacyAssetMapping.legacy_id.in_([row.file_id for row in rows]),
                    LegacyAssetMapping.target_type == "asset_version",
                )
            )).scalars())
            result["version_count"] = len(version_ids)
        document_ids = list(dict.fromkeys((await session.execute(
            select(AssetVersionDocument.document_id).where(
                AssetVersionDocument.version_id.in_(version_ids)
            )
        )).scalars()))
        result["document_count"] = len(document_ids)
        if not parse:
            return result

        parse_counts: dict[str, int] = {}
        for document_id in document_ids:
            try:
                parsed = await parse_asset_document(session, document_id)
                await session.commit()
                status = parsed["status"]
                parse_counts[status] = parse_counts.get(status, 0) + 1
            except Exception as exc:  # noqa: BLE001 - keep per-document checkpoint
                try:
                    await session.commit()
                except Exception:  # noqa: BLE001
                    await session.rollback()
                parse_counts["failed"] = parse_counts.get("failed", 0) + 1
                result["issues"].append({"document_id": document_id, "stage": "parse", "error": str(exc)[:200]})
        result["parse_counts"] = parse_counts
        return result


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="迁移复合制度资产V2标杆集")
    parser.add_argument("--apply", action="store_true", help="写入V2表；默认仅预览")
    parser.add_argument("--parse", action="store_true", help="逐文件建立解析快照和内容树")
    parser.add_argument("--title", help="仅处理一个现库标题")
    parser.add_argument("--all", action="store_true", dest="all_current", help="处理现库全部现行制度")
    parser.add_argument("--document-id", help="仅重新解析一个V2资产文件")
    parser.add_argument(
        "--current-status",
        choices=("pending", "running", "succeeded", "needs_review", "requires_ocr", "failed"),
        help="仅重新解析当前快照为指定状态的V2文件",
    )
    args = parser.parse_args()
    try:
        await load_runtime_model_config()
        print(json.dumps(
            await run(args.apply, args.parse, args.title, args.document_id, args.current_status, args.all_current),
            ensure_ascii=False,
            indent=2,
        ))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main_async())
