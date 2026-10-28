"""LLM adapter contract (architecture §7.4).

Implementations MUST NOT hard-code the 交融大模型 interface; selection happens
through ``factory.get_llm_adapter`` so the real model can be swapped in with zero
code changes once the OpenAI-compatible endpoint is available.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatResult:
    """Normalized chat completion result."""

    content: str
    finish_reason: str = "stop"
    usage: dict = field(default_factory=dict)
    model: str = ""
    raw: Any = None


class LLMAdapter(ABC):
    """Abstract chat adapter. Subclasses implement ``chat`` and (optionally) ``stream``."""

    kind: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 45.0,
    ) -> ChatResult:
        """Return a ChatResult for the given message list."""
        raise NotImplementedError

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1500,
        timeout: float = 45.0,
    ) -> AsyncIterator[str]:
        """Yield incremental text tokens for the given message list.

        Implementations that cannot stream fall back to yielding the full
        response as a single token.
        """
        raise NotImplementedError
