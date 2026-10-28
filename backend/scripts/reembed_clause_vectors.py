"""Re-embed current clauses whose stored vectors have a legacy dimension.

The command is intentionally fail-closed: real provider usage, explicit data
egress consent and a fresh SQLite backup are required before any row is changed.
Each successful batch is committed independently, so rerunning the command
continues from the remaining legacy vectors.

Examples:
    python -m scripts.reembed_clause_vectors --source-dim 128
    python -m scripts.reembed_clause_vectors --source-dim 128 --execute \
        --authorized-data-egress --backup-path devdata/run12.pre-reembed.db.bak
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from pathlib import Path
import sqlite3
import time

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.adapters.embedding.factory import get_embedding_adapter
from app.core.config import get_settings
from app.db.models.clause import Clause
from app.db.session import SessionLocal, dispose_engine
from app.services.ingestion.embed_job import _truncate
from app.services.model_runtime import load_runtime_model_config


def _sqlite_backup(destination: Path) -> None:
    url = make_url(get_settings().DATABASE_URL)
    if not url.drivername.startswith("sqlite") or not url.database:
        raise RuntimeError("automatic_backup_requires_sqlite")
    source = Path(url.database).resolve()
    destination = destination.resolve()
    if not source.is_file():
        raise RuntimeError("database_file_not_found")
    if destination.exists():
        raise RuntimeError("backup_path_already_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)


def _verify_sqlite_backup(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError("existing_backup_not_found")
    with sqlite3.connect(path) as database:
        result = database.execute("PRAGMA quick_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError("existing_backup_integrity_check_failed")


def _dimension_expression():
    """Return the SQLite JSON length expression used by this checkout."""
    return func.json_array_length(Clause.embedding)


async def _dimension_counts() -> Counter[int]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(_dimension_expression(), func.count(Clause.clause_id))
            .where(Clause.status == "current", Clause.embedding.isnot(None))
            .group_by(_dimension_expression())
        )
        return Counter({int(dim): int(count) for dim, count in rows if dim is not None})


async def run(
    *, source_dim: int, batch_size: int, execute: bool,
    authorized_data_egress: bool, backup_path: Path | None,
    reuse_backup: bool,
) -> int:
    await load_runtime_model_config()
    adapter = get_embedding_adapter()
    provider_kind = getattr(adapter, "kind", "unknown")
    target_dim = int(getattr(adapter, "dim", 0))
    before = await _dimension_counts()
    pending = before.get(source_dim, 0)
    print(f"PROVIDER_KIND: {provider_kind}")
    print(f"SOURCE_DIM: {source_dim}")
    print(f"TARGET_DIM: {target_dim}")
    print(f"PENDING: {pending}")

    if not execute:
        print("DRY_RUN: no database rows changed and no clause text sent")
        return 0
    if not authorized_data_egress:
        raise RuntimeError("explicit_data_egress_authorization_required")
    if provider_kind in {"mock", "unknown", "unconfigured"}:
        raise RuntimeError("real_embedding_provider_required")
    if target_dim <= 0 or target_dim == source_dim:
        raise RuntimeError("invalid_target_dimension")
    if backup_path is None:
        raise RuntimeError("backup_path_required")
    if pending == 0:
        print("DONE: no matching legacy vectors")
        return 0

    await dispose_engine()
    if reuse_backup:
        _verify_sqlite_backup(backup_path)
    else:
        _sqlite_backup(backup_path)
    print(f"BACKUP: {backup_path.resolve()}")

    completed = 0
    started = time.perf_counter()
    while True:
        async with SessionLocal() as session:
            clauses = list((await session.execute(
                select(Clause)
                .where(
                    Clause.status == "current",
                    Clause.embedding.isnot(None),
                    _dimension_expression() == source_dim,
                )
                .order_by(Clause.clause_id)
                .limit(batch_size)
            )).scalars())
            if not clauses:
                break
            texts = [f"{clause.clause_no} {_truncate(clause.content)}" for clause in clauses]
            vectors = await asyncio.to_thread(adapter.embed, texts)
            if len(vectors) != len(clauses):
                raise RuntimeError("provider_vector_count_mismatch")
            if any(len(vector) != target_dim for vector in vectors):
                raise RuntimeError("provider_vector_dimension_mismatch")
            for clause, vector in zip(clauses, vectors, strict=True):
                clause.embedding = vector
            await session.commit()
            completed += len(clauses)
            elapsed = max(time.perf_counter() - started, 0.001)
            print(
                f"PROGRESS: completed={completed}/{pending} "
                f"remaining={max(pending - completed, 0)} rate={completed / elapsed:.2f}/s",
                flush=True,
            )

    after = await _dimension_counts()
    remaining = after.get(source_dim, 0)
    target_count = after.get(target_dim, 0)
    print(f"FINAL: completed={completed} remaining_source_dim={remaining} target_dim_count={target_count}")
    if remaining:
        raise RuntimeError("legacy_vectors_remain")
    return 0


async def _run_with_cleanup(**kwargs) -> int:
    try:
        return await run(**kwargs)
    finally:
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dim", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=10, choices=range(1, 51))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--authorized-data-egress", action="store_true")
    parser.add_argument("--backup-path", type=Path)
    parser.add_argument(
        "--reuse-backup", action="store_true",
        help="断点续跑时复用并校验已存在的SQLite备份",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run_with_cleanup(
            source_dim=args.source_dim,
            batch_size=args.batch_size,
            execute=args.execute,
            authorized_data_egress=args.authorized_data_egress,
            backup_path=args.backup_path,
            reuse_backup=args.reuse_backup,
        ))
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
