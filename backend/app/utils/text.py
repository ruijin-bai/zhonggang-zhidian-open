"""Lightweight text tokenisation and keyword helpers."""
from __future__ import annotations

import re

def tokenize(text: str) -> list[str]:
    """Lightweight tokens: latin words + CJK char/bigram units."""
    text = (text or "").lower()
    tokens: list[str] = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[一-鿿]", text)
    for i, ch in enumerate(cjk):
        tokens.append(f"c:{ch}")
        if i + 1 < len(cjk):
            tokens.append(f"b:{cjk[i]}{cjk[i + 1]}")
    return tokens


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(k in (text or "") for k in keywords)
