"""Mock LLM / Embedding adapter tests — ensure the no-key path works (T04)."""
from __future__ import annotations

import numpy as np

from app.adapters.embedding.mock import MockEmbeddingAdapter
from app.adapters.llm.mock import MockLLMAdapter


def test_mock_embedding_deterministic_and_similar():
    emb = MockEmbeddingAdapter()
    v1 = emb.embed(["境外项目变更款审批权限"])[0]
    v2 = emb.embed(["境外项目变更款由谁审批"])[0]
    v3 = emb.embed(["今天天气晴朗适合出游"])[0]
    assert v1 == emb.embed(["境外项目变更款审批权限"])[0]  # deterministic

    def cos(a, b):
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    assert cos(v1, v2) > cos(v1, v3)  # related > unrelated


async def test_mock_llm_assembles_partitioned_answer():
    llm = MockLLMAdapter()
    prompt = (
        "用户问题：境外项目变更款50万美元由谁审批\n\n"
        "【检索到的制度条款】\n"
        '<<CLAUSE file="境外项目管理办法" no="第12条">>\n'
        "境外项目变更款超过50万美元须报区域总经理审核后报总部审批。\n"
        "<</CLAUSE>>"
    )
    result = await llm.chat([{"role": "user", "content": prompt}])
    assert "适用制度" in result.content
    assert "总部" in result.content
    assert "境外项目管理办法" in result.content
