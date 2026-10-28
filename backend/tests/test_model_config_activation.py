"""Atomic, permissioned model-configuration activation tests."""
from __future__ import annotations

import httpx
import pytest

from app.adapters.embedding.factory import get_embedding_adapter, reset_embedding_adapter
from app.adapters.embedding.openai_compat import OpenAICompatEmbeddingAdapter
from app.adapters.llm.base import ChatResult
from app.adapters.llm.factory import get_llm_adapter, reset_llm_adapter
from app.adapters.llm.openai_compat import OpenAICompatLLMAdapter
from app.core.runtime_config import (
    RuntimeModelConfig,
    get_runtime_model_config,
    set_runtime_model_config,
)
from app.core.secret_vault import decrypt_secret
from app.core.security import hash_password
from app.db.models.model_config import ModelConfig
from app.db.models.user import User
from app.main import app


@pytest.fixture(autouse=True)
def restore_runtime_config():
    previous = get_runtime_model_config()
    try:
        yield
    finally:
        set_runtime_model_config(previous)
        reset_llm_adapter()
        reset_embedding_adapter()


async def _seed_user(session, username: str, role: str) -> None:
    session.add(
        User(
            user_id=f"u_{username}",
            username=username,
            hashed_password=hash_password("Zhonggang@123"),
            role=role,
            secret_clearance="secret",
            is_active=True,
        )
    )
    await session.commit()


async def _headers(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Zhonggang@123"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['data']['access_token']}"}


def _real_payload(**overrides) -> dict:
    data = {
        "enabled": True,
        "llm_base_url": "https://candidate.example/v1",
        "llm_api_key": "new-llm-key",
        "llm_model": "candidate-chat",
        "llm_timeout": 6.0,
        "embed_base_url": "https://candidate.example/v1",
        "embed_api_key": "new-embed-key",
        "embed_model": "candidate-embedding",
        "embed_dim": 256,
    }
    data.update(overrides)
    return data


async def test_failed_validation_never_overwrites_active_config(session, monkeypatch) -> None:
    await _seed_user(session, "model_admin_fail", "R4")
    current = ModelConfig(
        id="singleton", enabled=True,
        llm_base_url="https://active.example/v1", llm_api_key="active-llm-key", llm_model="active-chat",
        embed_base_url="https://active.example/v1", embed_api_key="active-embed-key", embed_model="active-embedding",
        embed_dim=1024,
    )
    session.add(current)
    await session.commit()
    set_runtime_model_config(RuntimeModelConfig(enabled=True, llm_api_key="active-llm-key", llm_model="active-chat"))

    async def failing_chat(self, *_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    def failing_embed(self, *_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(OpenAICompatLLMAdapter, "chat", failing_chat)
    monkeypatch.setattr(OpenAICompatEmbeddingAdapter, "embed", failing_embed)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/v1/system/model-config",
            json=_real_payload(),
            headers=await _headers(client, "model_admin_fail"),
        )

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == 40001
    assert body["data"] == {
        "llm_ok": False,
        "embed_ok": False,
        "llm_error": "连接失败（RuntimeError）",
        "embed_error": "连接失败（RuntimeError）",
    }
    await session.refresh(current)
    assert current.llm_model == "active-chat"
    assert current.embed_dim == 1024
    assert current.enabled is True
    assert get_runtime_model_config().llm_model == "active-chat"


async def test_successful_dual_check_atomically_saves_and_enables(session, monkeypatch) -> None:
    await _seed_user(session, "model_admin_ok", "R4")

    async def successful_chat(self, *_args, **_kwargs):
        return ChatResult(content="ok")

    def successful_embed(self, *_args, **_kwargs):
        return [[0.1, 0.2]]

    monkeypatch.setattr(OpenAICompatLLMAdapter, "chat", successful_chat)
    monkeypatch.setattr(OpenAICompatEmbeddingAdapter, "embed", successful_embed)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/v1/system/model-config",
            json=_real_payload(),
            headers=await _headers(client, "model_admin_ok"),
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["enabled"] is True
    assert data["llm_api_key"] == "new-****-key"
    assert data["embed_api_key"] == "new-****-key"
    saved = await session.get(ModelConfig, "singleton")
    assert saved is not None
    assert saved.enabled is True
    assert saved.llm_model == "candidate-chat"
    assert saved.embed_dim == 256
    assert saved.llm_api_key.startswith("enc:v1:")
    assert decrypt_secret(saved.llm_api_key) == "new-llm-key"
    assert get_runtime_model_config().enabled is True
    assert get_runtime_model_config().embed_model == "candidate-embedding"


async def test_offline_switch_uses_mock_without_erasing_saved_real_config(session) -> None:
    await _seed_user(session, "model_admin_offline", "R4")
    saved = ModelConfig(
        id="singleton", enabled=True,
        llm_base_url="https://active.example/v1", llm_api_key="active-llm-key", llm_model="active-chat",
        embed_base_url="https://active.example/v1", embed_api_key="active-embed-key", embed_model="active-embedding",
        embed_dim=1024,
    )
    session.add(saved)
    await session.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/v1/system/model-config",
            json={"enabled": False},
            headers=await _headers(client, "model_admin_offline"),
        )

    assert response.status_code == 200, response.text
    await session.refresh(saved)
    assert saved.enabled is False
    assert decrypt_secret(saved.llm_api_key) == "active-llm-key"
    assert decrypt_secret(saved.embed_api_key) == "active-embed-key"
    assert get_runtime_model_config().enabled is False
    assert get_llm_adapter().kind == "mock"
    assert get_embedding_adapter().kind == "mock"


async def test_model_config_update_is_r4_only(session) -> None:
    await _seed_user(session, "model_employee", "R1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/v1/system/model-config",
            json={"enabled": False},
            headers=await _headers(client, "model_employee"),
        )
    assert response.status_code == 403
    assert response.json()["code"] == 40301
