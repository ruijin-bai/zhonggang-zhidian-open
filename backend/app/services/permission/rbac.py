"""RBAC permission filter (architecture §7.5).

``build_filter`` returns a SQLAlchemy boolean expression over ``RegulationFile``
combining, for every permission row of the user:
    (scope = '/' OR org_path IN scope's complete path ancestors)  AND
    secret_level <= min(user, role clearance)  AND  (domain='*' OR domain match)
A scope of "/" is the company-wide wildcard.  Otherwise a regulation is visible
when the user's org scope falls inside the regulation's org_path (the
regulation range contains the user).  The retriever (and clause / graph
queries) MUST inject this predicate so that unauthorised content never enters
retrieval or answers.
"""
from __future__ import annotations

from sqlalchemy import and_, false, or_, true
from sqlalchemy.sql import ColumnElement

from app.db.enums import SecretLevel
from app.db.models.permission import Permission
from app.db.models.regulation import RegulationFile
from app.db.models.user import User

# Ordered least → most secret (matches SecretLevel.rank).
_SECRET_ORDER = [SecretLevel.PUBLIC.value, SecretLevel.INTERNAL.value, SecretLevel.CONFIDENTIAL.value, SecretLevel.SECRET.value]


def _levels_at_most(level: str) -> list[str]:
    try:
        idx = _SECRET_ORDER.index(level)
    except ValueError:
        idx = 0
    return _SECRET_ORDER[: idx + 1]


def _effective_secret_level(user_level: str, permission_level: str) -> str:
    """Return the lower of a user's clearance and a role permission ceiling."""
    try:
        user_rank = _SECRET_ORDER.index(user_level)
    except ValueError:
        user_rank = 0
    try:
        permission_rank = _SECRET_ORDER.index(permission_level)
    except ValueError:
        permission_rank = 0
    return _SECRET_ORDER[min(user_rank, permission_rank)]


def _organization_filter(scope: str, org_path: ColumnElement) -> ColumnElement:
    """Allow a resource whose complete organisation path contains the scope.

    Exact ancestors avoid sibling prefixes and SQL LIKE metacharacters. Each
    ancestor accepts the canonical path and its legacy trailing-slash form.
    Only the explicit company-wide scope '/' bypasses organisation filtering.
    """
    if scope == "/":
        return true()
    if not isinstance(scope, str) or not scope.startswith("/"):
        return false()
    parts = scope.rstrip("/").split("/")[1:]
    if not parts or any(not part or part in {".", ".."} for part in parts):
        return false()
    ancestors = ["/"]
    current = ""
    for part in parts:
        current += "/" + part
        ancestors.extend((current, current + "/"))
    return org_path.in_(ancestors)


def build_filter(
    user: User | None,
    permissions: list[Permission],
    clause_secret_level: ColumnElement | None = None,
) -> ColumnElement:
    """Build an RBAC predicate for regulations and, optionally, their clauses.

    A clause is visible only if both its containing regulation and the clause
    itself are at or below the same effective clearance.  Passing the clause
    column keeps the org/domain/role permission bound to the matching policy
    row instead of applying a weaker global maximum after the fact.
    """
    if not permissions:
        return false()

    conditions = []
    for perm in permissions:
        org_ok = _organization_filter(perm.org_scope, RegulationFile.org_path)
        user_level = user.secret_clearance if user is not None else perm.secret_level
        allowed_levels = _levels_at_most(_effective_secret_level(user_level, perm.secret_level))
        secret_ok = RegulationFile.secret_level.in_(allowed_levels)
        clause_secret_ok = (
            true() if clause_secret_level is None else clause_secret_level.in_(allowed_levels)
        )
        # ``perm.domain`` is a plain Python value, not a column, so we build a
        # SQL boolean expression (true() = all domains) instead of using ``|``.
        domain_ok = true() if perm.domain == "*" else (RegulationFile.domain == perm.domain)
        conditions.append(and_(org_ok, secret_ok, clause_secret_ok, domain_ok))

    return or_(*conditions)


def build_asset_filter(
    user: User | None,
    permissions: list[Permission],
    *,
    secret_level: ColumnElement,
    org_path: ColumnElement,
    domain: ColumnElement,
    content_secret_level: ColumnElement | None = None,
) -> ColumnElement:
    """Build the same RBAC gate for V2 compound knowledge assets.

    V2 deliberately does not masquerade as ``RegulationFile`` at the SQL
    boundary.  Supplying the three asset columns keeps organisation, domain and
    secrecy checks inside the database query, before any text or vector leaves
    the authorised candidate set.
    """
    if not permissions:
        return false()

    conditions = []
    for perm in permissions:
        org_ok = _organization_filter(perm.org_scope, org_path)
        user_level = user.secret_clearance if user is not None else perm.secret_level
        allowed_levels = _levels_at_most(_effective_secret_level(user_level, perm.secret_level))
        domain_ok = true() if perm.domain == "*" else (domain == perm.domain)
        content_ok = (
            true() if content_secret_level is None else content_secret_level.in_(allowed_levels)
        )
        conditions.append(and_(org_ok, secret_level.in_(allowed_levels), content_ok, domain_ok))
    return or_(*conditions)


def viz_permissions(permissions: list[Permission]) -> list[dict]:
    """Human-readable permission summary for /users/me."""
    return [
        {
            "role": p.role,
            "org_scope": p.org_scope,
            "secret_level": p.secret_level,
            "domain": p.domain,
        }
        for p in permissions
    ]
