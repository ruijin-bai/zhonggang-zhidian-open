"""Route-registration test for the canonical clause-detail endpoint (T-fix).

Ensures ``GET /api/v1/clauses/{clause_id}`` is served (the path the frontend
原文溯源 page actually calls) and that the legacy
``/api/v1/regulations/clauses/{clause_id}`` route remains registered (no
breaking change).

We assert against the generated OpenAPI schema rather than ``app.routes[*].path``
because in this FastAPI/Starlette version the per-route ``path`` attribute is not
populated for included routers; the OpenAPI ``paths`` map is the authoritative
registry of mounted routes.
"""
from __future__ import annotations

from app.main import app


def _registered_paths() -> set[str]:
    return set(app.openapi().get("paths", {}).keys())


def test_canonical_clause_route_registered() -> None:
    assert "/api/v1/clauses/{clause_id}" in _registered_paths()


def test_canonical_clause_route_is_get() -> None:
    methods = app.openapi()["paths"]["/api/v1/clauses/{clause_id}"].keys()
    assert "get" in methods


def test_legacy_clause_route_still_registered() -> None:
    assert "/api/v1/regulations/clauses/{clause_id}" in _registered_paths()
