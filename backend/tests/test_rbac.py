"""RBAC permission filter unit tests (architecture §7.5)."""
from __future__ import annotations

from sqlalchemy import false, select

from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.services.permission.rbac import _levels_at_most, build_filter


def test_levels_at_most_orders_correctly():
    assert _levels_at_most("internal") == ["public", "internal"]
    assert "confidential" in _levels_at_most("confidential")
    assert _levels_at_most("secret")[-1] == "secret"


def test_empty_permissions_deny_everything():
    expr = build_filter(None, [])
    assert str(expr) == str(false())


def test_permission_filter_injects_predicates():
    perm = Permission(role="R4", org_scope="/hq", secret_level="secret", domain="*")
    expr = build_filter(None, [perm])
    sql = str(select(RegulationFile).where(expr))
    assert "regulation_file.org_path IN" in sql
    assert "regulation_file.secret_level IN" in sql
    assert "LIKE" not in sql
