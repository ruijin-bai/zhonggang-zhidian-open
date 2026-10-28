from pathlib import Path


def test_ci_runs_all_required_offline_gates():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for required in (
        "push:", "pull_request:", "python -m pytest -q", "python -m scripts.check_migrations",
        "npm ci", "npm run build", "docker compose config --quiet",
        "LLM_PROVIDER: mock", "EMBED_PROVIDER: mock", "DATABASE_URL: sqlite+aiosqlite",
    ):
        assert required in workflow
    assert "API_KEY" not in workflow
