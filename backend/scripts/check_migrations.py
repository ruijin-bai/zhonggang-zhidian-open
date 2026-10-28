"""Static Alembic revision-chain check for the release gate.

This intentionally parses source only: it does not connect to a database, run
migrations, create tables, or change any data.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "alembic" / "versions"


def _assignment(tree: ast.Module, name: str, path: Path):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError as exc:
                        raise ValueError(f"{path.name}: {name} must be a literal") from exc
    raise ValueError(f"{path.name}: missing {name} assignment")


def _parents(value, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (tuple, list)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ValueError(f"{path.name}: down_revision must be None, a string, or a string sequence")


def main() -> int:
    errors: list[str] = []
    if not (ROOT / "alembic.ini").is_file():
        errors.append("missing alembic.ini")
    if not (ROOT / "alembic" / "env.py").is_file():
        errors.append("missing alembic/env.py")
    files = sorted(path for path in VERSIONS.glob("*.py") if path.name != "__init__.py") if VERSIONS.is_dir() else []
    if not files:
        errors.append("no revision files under alembic/versions")

    revisions: dict[str, tuple[Path, tuple[str, ...]]] = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            revision = _assignment(tree, "revision", path)
            if not isinstance(revision, str) or not revision:
                raise ValueError(f"{path.name}: revision must be a non-empty string")
            parents = _parents(_assignment(tree, "down_revision", path), path)
            if revision in revisions:
                raise ValueError(f"duplicate revision {revision!r} ({path.name} and {revisions[revision][0].name})")
            revisions[revision] = (path, parents)
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(str(exc))

    if not errors:
        for revision, (path, parents) in revisions.items():
            for parent in parents:
                if parent not in revisions:
                    errors.append(f"{path.name}: down_revision {parent!r} does not exist")

        def visit(revision: str, visiting: set[str], visited: set[str]) -> None:
            if revision in visiting:
                errors.append(f"cycle detected at revision {revision!r}")
                return
            if revision in visited:
                return
            visiting.add(revision)
            for parent in revisions[revision][1]:
                visit(parent, visiting, visited)
            visiting.remove(revision)
            visited.add(revision)

        visited: set[str] = set()
        for revision in revisions:
            visit(revision, set(), visited)

    if errors:
        print("MIGRATION_CHECK_FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    parents = {parent for _, parent_list in revisions.values() for parent in parent_list}
    heads = sorted(set(revisions) - parents)
    roots = sorted(revision for revision, (_, parent_list) in revisions.items() if not parent_list)
    print(f"MIGRATION_CHECK_OK revisions={len(revisions)} roots={','.join(roots)} heads={','.join(heads)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
