"""Verify rule-source migration in new, synthetic databases only.

No --database argument is provided. The script never reads an application DB.
PostgreSQL is an offline 0019->0020 DDL compilation, not a live DB acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parent


def _environment(database_url):
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": database_url, "ENVIRONMENT": "dev", "LLM_PROVIDER": "mock",
        "EMBED_PROVIDER": "mock", "VECTOR_BACKEND": "memory", "EMBED_DIM": "128",
        "LLM_API_KEY": "", "EMBED_API_KEY": "", "RERANK_API_KEY": "", "RERANK_ENABLED": "false",
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
    })
    return env


def _alembic(database_url, operation, target, *, offline=False):
    args = [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), operation, target]
    if offline:
        args.append("--sql")
    return subprocess.run(args, cwd=ROOT, env=_environment(database_url), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


def _reflect(conn, name):
    return sa.Table(name, sa.MetaData(), autoload_with=conn)


def _insert(conn, table_name, **values):
    # Reflect the actual revision's schema, never the current ORM's columns.
    table = _reflect(conn, table_name)
    for column in table.columns:
        if column.name in values or column.nullable or column.server_default is not None:
            continue
        if isinstance(column.type, sa.JSON): values[column.name] = {}
        elif isinstance(column.type, sa.Boolean): values[column.name] = True
        elif isinstance(column.type, sa.Integer): values[column.name] = 0
        elif isinstance(column.type, sa.DateTime): values[column.name] = datetime.now(timezone.utc)
        elif isinstance(column.type, sa.Date): values[column.name] = date.today()
        elif isinstance(column.type, sa.String): values[column.name] = "synthetic"
        else: raise AssertionError(f"Explicit synthetic value required for {table_name}.{column.name}")
    conn.execute(table.insert().values(**values))


def _legacy_seed(conn):
    _insert(conn, "org_unit", org_id="synthetic-migration-org", name="Synthetic migration owner", path="/synthetic")
    _insert(conn, "user", user_id="synthetic-migration-user", username="synthetic-migration-user", hashed_password="unused-synthetic-only", role="R4", secret_clearance="internal", org_id="synthetic-migration-org")
    _insert(conn, "regulation_file", file_id="synthetic-legacy-file", title="Synthetic legacy source", regulation_code="SYN-MIG-001", source="synthetic test fixture", version="v1", status="current", owner_org="synthetic-migration-org", org_path="/synthetic", domain="synthetic", secret_level="internal", lang="zh", effective_date=date(2026, 1, 1), parse_backend="synthetic", parse_quality_report={})
    _insert(conn, "clause", clause_id="synthetic-legacy-clause", file_id="synthetic-legacy-file", clause_no="Synthetic clause 1", content="Synthetic source text; no business claim.", status="current", secret_level="internal", scenario_tags=["contract_change"], heading_path=[], block_type="paragraph", content_hash="a" * 64)
    _insert(conn, "decision_rule", rule_id="synthetic-legacy-rule", rule_key="synthetic-legacy-rule", scenario="contract_change", rule_type="approval", priority=100, status="current", file_id="synthetic-legacy-file", clause_id="synthetic-legacy-clause", currency="USD", min_inclusive=True, max_inclusive=True, org_scope="/synthetic", conditions={}, approver_path=["Synthetic approver"], required_materials=["Synthetic material"], created_by="synthetic-migration-user", reviewed_by="synthetic-migration-user", reviewed_at=datetime.now(timezone.utc))


def _legacy_snapshot(conn):
    rule = _reflect(conn, "decision_rule")
    fields = ["rule_id", "rule_key", "file_id", "clause_id", "status", "currency", "approver_path", "required_materials", "reviewed_by"]
    row = conn.execute(sa.select(*(rule.c[name] for name in fields)).where(rule.c.rule_id == "synthetic-legacy-rule")).mappings().one()
    file_title = conn.execute(sa.text("SELECT title FROM regulation_file WHERE file_id='synthetic-legacy-file'")).scalar_one()
    clause_text = conn.execute(sa.text("SELECT content FROM clause WHERE clause_id='synthetic-legacy-clause'")).scalar_one()
    return {"rule": dict(row), "file_title": file_title, "clause_content": clause_text}


def _evidence_fingerprints(conn):
    """Compare complete synthetic rule/source rows, not only foreign-key IDs."""
    snapshots = {}
    for name in ("decision_rule", "regulation_file", "clause", "knowledge_asset", "asset_version", "retrieval_unit"):
        table = _reflect(conn, name)
        rows = [dict(row) for row in conn.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings()]
        encoded = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        snapshots[name] = {"row_count": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}
    return snapshots


def _v2_seed(conn):
    _insert(conn, "knowledge_asset", asset_id="synthetic-v2-asset", asset_type="management_method", title="Synthetic V2 source", business_code="SYN-MIG-V2", owner_org="synthetic-migration-org", org_path="/synthetic", secret_level="internal", domain="synthetic", lang="zh", status="active", governance_metadata={})
    _insert(conn, "asset_version", version_id="synthetic-v2-version", asset_id="synthetic-v2-asset", version_label="v1", release_state="current", ingestion_state="ready", effective_date=date(2026, 1, 1), issuer="Synthetic issuer", issue_no="SYN-MIG-V2", version_metadata={})
    _insert(conn, "retrieval_unit", unit_id="synthetic-v2-unit", version_id="synthetic-v2-version", unit_type="article", title="Synthetic clause", text="Synthetic V2 rule migration fixture.", content_hash="b" * 64, secret_level="internal", status="verified", unit_metadata={})
    _insert(conn, "decision_rule", rule_id="synthetic-v2-rule", rule_key="synthetic-v2-rule", scenario="contract_change", rule_type="approval", priority=100, status="current", source_kind="asset", file_id=None, clause_id=None, asset_version_id="synthetic-v2-version", retrieval_unit_id="synthetic-v2-unit", currency="USD", min_inclusive=True, max_inclusive=True, org_scope="/synthetic", conditions={}, approver_path=["Synthetic approver"], required_materials=["Synthetic material"])


def _schema_report(conn):
    inspector = sa.inspect(conn)
    columns = {column["name"]: {"type": str(column["type"]), "nullable": column["nullable"], "default": column["default"]} for column in inspector.get_columns("decision_rule")}
    foreign_keys = inspector.get_foreign_keys("decision_rule")
    indexes = inspector.get_indexes("decision_rule")
    assert columns["source_kind"]["type"] == "VARCHAR(16)" and not columns["source_kind"]["nullable"]
    assert "regulation" in str(columns["source_kind"]["default"])
    for name in ["file_id", "clause_id", "asset_version_id", "retrieval_unit_id"]:
        assert columns[name]["type"] == "VARCHAR(32)" and columns[name]["nullable"]
    fk_targets = {(tuple(item["constrained_columns"]), item["referred_table"]) for item in foreign_keys}
    for name, target in [("file_id", "regulation_file"), ("clause_id", "clause"), ("asset_version_id", "asset_version"), ("retrieval_unit_id", "retrieval_unit")]:
        assert ((name,), target) in fk_targets
    index_columns = {tuple(item["column_names"]) for item in indexes}
    assert ("asset_version_id",) in index_columns and ("retrieval_unit_id",) in index_columns
    violations = conn.execute(sa.text("PRAGMA foreign_key_check")).all()
    assert not violations
    return {"columns": columns, "foreign_keys": foreign_keys, "indexes": indexes, "foreign_key_violations": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPOSITORY / ".runtime/acceptance/migration-acceptance.json")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(REPOSITORY.resolve()):
        raise ValueError("Report must remain inside the repository; database locations are not configurable")
    temp_root = Path(tempfile.mkdtemp(prefix="zg-rule-migration-acceptance-")).resolve()
    database = (temp_root / "synthetic-migration.db").resolve()
    assert database.parent == temp_root and not database.exists()
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "all_passed": False, "isolation": {"temporary_directory": str(temp_root), "new_database": str(database), "original_database_used": False, "synthetic_seed_only": True}, "checks": {}}
    engine = sa.create_engine("sqlite:///" + database.as_posix())
    @sa.event.listens_for(engine, "connect")
    def enable_fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    def migrate(operation, target):
        assert database.resolve().parent == temp_root
        result = _alembic("sqlite:///" + database.as_posix(), operation, target)
        if result.returncode:
            raise RuntimeError(result.stderr[-8000:])
        return result

    try:
        pg = _alembic("postgresql+psycopg://offline:unused@offline.invalid/offline_compile", "upgrade", "0019:0020", offline=True)
        assert pg.returncode == 0, pg.stderr[-8000:]
        for expected in (
            "ADD COLUMN source_kind VARCHAR(16) DEFAULT 'regulation' NOT NULL",
            "ALTER COLUMN file_id DROP NOT NULL", "ALTER COLUMN clause_id DROP NOT NULL",
            "ADD COLUMN asset_version_id VARCHAR(32)", "ADD COLUMN retrieval_unit_id VARCHAR(32)",
            "FOREIGN KEY(asset_version_id) REFERENCES asset_version (version_id)",
            "FOREIGN KEY(retrieval_unit_id) REFERENCES retrieval_unit (unit_id)",
            "CREATE INDEX ix_decision_rule_asset_version_id", "CREATE INDEX ix_decision_rule_retrieval_unit_id",
        ):
            assert expected in pg.stdout, f"Offline PostgreSQL DDL missing: {expected}"
        sql_path = output.with_name("rule-source-upgrade-0020.postgresql.sql")
        sql_path.parent.mkdir(parents=True, exist_ok=True)
        sql_path.write_text(pg.stdout, encoding="utf-8")
        report["checks"]["postgresql_offline_upgrade"] = {"passed": True, "revision_range": "0019:0020", "sql_file": str(sql_path), "sha256": hashlib.sha256(pg.stdout.encode()).hexdigest(), "live_postgresql_connected": False, "server_execution_verified": False}
        migrate("upgrade", "head")
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0021"
            report["checks"]["fresh_upgrade_to_head"] = {"passed": True, "head": "0021", "table_count": len(sa.inspect(conn).get_table_names())}
        # An empty head->0019 downgrade produces the actual legacy schema even
        # though migration 0001 bootstraps from today's ORM metadata.
        migrate("downgrade", "0019")
        with engine.begin() as conn:
            assert "source_kind" not in {column["name"] for column in sa.inspect(conn).get_columns("decision_rule")}
            _legacy_seed(conn)
            baseline = _legacy_snapshot(conn)
        migrate("upgrade", "0020")
        with engine.connect() as conn:
            assert _legacy_snapshot(conn) == baseline
            row = conn.execute(sa.text("SELECT source_kind,asset_version_id,retrieval_unit_id FROM decision_rule WHERE rule_id='synthetic-legacy-rule'")).one()
            assert tuple(row) == ("regulation", None, None)
            report["checks"]["legacy_upgrade_preservation"] = {"passed": True, "ids": {"file_id": "synthetic-legacy-file", "clause_id": "synthetic-legacy-clause", "rule_id": "synthetic-legacy-rule"}, "source_kind_default": "regulation", "legacy_row_and_evidence_unchanged": True}
            report["checks"]["sqlite_schema_and_foreign_keys"] = {"passed": True, **_schema_report(conn)}
        migrate("downgrade", "0019")
        with engine.connect() as conn:
            assert _legacy_snapshot(conn) == baseline
            assert "source_kind" not in {column["name"] for column in sa.inspect(conn).get_columns("decision_rule")}
        migrate("upgrade", "0020")
        with engine.begin() as conn:
            assert _legacy_snapshot(conn) == baseline
            _v2_seed(conn)
            try:
                with conn.begin_nested():
                    conn.execute(sa.text("UPDATE decision_rule SET asset_version_id='missing-version' WHERE rule_id='synthetic-v2-rule'"))
            except sa.exc.IntegrityError:
                pass
            else:
                raise AssertionError("SQLite foreign-key enforcement allowed an invalid V2 source")
            assert not conn.execute(sa.text("PRAGMA foreign_key_check")).all()
            before = conn.execute(sa.text("SELECT rule_id,source_kind,file_id,clause_id,asset_version_id,retrieval_unit_id FROM decision_rule ORDER BY rule_id")).all()
            before_evidence = _evidence_fingerprints(conn)
        report["checks"]["legacy_roundtrip"] = {"passed": True, "revision_sequence": ["0019", "0020", "0019", "0020"], "legacy_row_and_evidence_unchanged": True}
        report["checks"]["sqlite_fk_enforced"] = {"passed": True, "invalid_asset_reference_rejected": True}
        refusal = _alembic("sqlite:///" + database.as_posix(), "downgrade", "0019")
        assert refusal.returncode != 0 and "回退会丢失证据" in refusal.stderr, refusal.stderr[-8000:]
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0020"
            after = conn.execute(sa.text("SELECT rule_id,source_kind,file_id,clause_id,asset_version_id,retrieval_unit_id FROM decision_rule ORDER BY rule_id")).all()
            assert before == after and _legacy_snapshot(conn) == baseline
            assert before_evidence == _evidence_fingerprints(conn)
            assert not conn.execute(sa.text("PRAGMA foreign_key_check")).all()
        report["checks"]["v2_downgrade_refused_without_loss"] = {"passed": True, "head_retained": "0020", "rule_count_retained": len(after), "source_rows_unchanged": True, "complete_row_fingerprints": before_evidence}
        report["all_passed"] = True
    except Exception as exc:
        report["failure"] = str(exc)
    finally:
        engine.dispose()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"all_passed": report["all_passed"], "checks_passed": len(report["checks"]), "output": str(output), "failure": report.get("failure")}, ensure_ascii=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
