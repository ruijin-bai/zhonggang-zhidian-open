"""Verify 0021 using synthetic databases; never accepts an application DB."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import sqlalchemy as sa

from scripts.verify_rule_source_migration import _alembic, _legacy_seed, _legacy_snapshot, REPOSITORY


def main():
    output = REPOSITORY / ".runtime/acceptance/source-confirmation-migration.json"
    report = {"all_passed": False, "checks": {}, "database_scope": "new synthetic SQLite databases only"}
    engine = None
    try:
        with tempfile.TemporaryDirectory(prefix="zg-source-migration-") as folder:
            path = Path(folder) / "synthetic.db"
            url = "sqlite:///" + path.as_posix()
            def migrate(operation, target):
                result = _alembic(url, operation, target)
                assert result.returncode == 0, result.stderr[-8000:]
            migrate("upgrade", "0020")
            engine = sa.create_engine(url)
            with engine.begin() as conn:
                _legacy_seed(conn)
                baseline = _legacy_snapshot(conn)
            migrate("upgrade", "0021")
            with engine.connect() as conn:
                assert _legacy_snapshot(conn) == baseline
                assert json.loads(conn.execute(sa.text("SELECT source_confirmation FROM regulation_file")).scalar_one()) == {}
            report["checks"]["upgrade_preserves_source_and_rule"] = True
            migrate("downgrade", "0020")
            with engine.connect() as conn:
                assert _legacy_snapshot(conn) == baseline
                assert "source_confirmation" not in {row["name"] for row in sa.inspect(conn).get_columns("regulation_file")}
            migrate("upgrade", "0021")
            report["checks"]["empty_confirmation_roundtrip"] = True
            confirmation = {"kind": "maintainer", "confirmed": True, "actor_id": "synthetic-migration-user",
                "confirmed_at": "2026-10-01T12:00:00+00:00", "note": "Synthetic migration fixture only"}
            with engine.begin() as conn:
                conn.execute(sa.text("UPDATE regulation_file SET source_confirmation=:value"), {"value": json.dumps(confirmation)})
            refusal = _alembic(url, "downgrade", "0020")
            assert refusal.returncode != 0 and "回退会丢失确认记录" in refusal.stderr, refusal.stderr[-8000:]
            with engine.connect() as conn:
                assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0021"
                assert json.loads(conn.execute(sa.text("SELECT source_confirmation FROM regulation_file")).scalar_one()) == confirmation
                assert _legacy_snapshot(conn) == baseline
                assert not conn.execute(sa.text("PRAGMA foreign_key_check")).all()
            report["checks"]["confirmed_source_downgrade_refused_without_loss"] = True
            fresh = "sqlite:///" + (Path(folder) / "fresh.db").as_posix()
            result = _alembic(fresh, "upgrade", "head")
            assert result.returncode == 0, result.stderr[-8000:]
            fresh_engine = sa.create_engine(fresh)
            with fresh_engine.connect() as conn:
                assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0021"
                assert "source_confirmation" in {row["name"] for row in sa.inspect(conn).get_columns("regulation_file")}
            fresh_engine.dispose()
            report["checks"]["fresh_head_0021"] = True
            pg = _alembic("postgresql+psycopg://offline:unused@offline.invalid/offline_compile", "upgrade", "0020:0021", offline=True)
            assert pg.returncode == 0 and "ADD COLUMN source_confirmation JSON" in pg.stdout, pg.stderr[-8000:]
            output.with_suffix(".postgresql.sql").write_text(pg.stdout, encoding="utf-8")
            report["checks"]["postgresql_offline_ddl_only"] = True
            engine.dispose()
            engine = None
        report["all_passed"] = True
    except Exception as error:
        report["failure"] = str(error)
    finally:
        if engine is not None:
            engine.dispose()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
