"""Deterministic parse-quality scoring and publication gate."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict

from app.services.ingestion.parser import RawClause


@dataclass
class ParseQualityReport:
    score: int
    passed: bool
    backend: str
    clause_count: int
    source_chars: int
    parsed_chars: int
    coverage: float
    max_clause_chars: int
    p95_clause_chars: int
    anchored_ratio: float
    warnings: list[str]

    def model_dump(self) -> dict:
        return asdict(self)


def _visible(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def assess_parse_quality(
    source_text: str, clauses: list[RawClause], *, backend: str, filename: str = "",
    minimum_score: int = 72,
) -> ParseQualityReport:
    source = _visible(source_text)
    contents = [_visible(item.content) for item in clauses if _visible(item.content)]
    lengths = sorted(len(item) for item in contents)
    parsed_chars = sum(lengths)
    source_chars = len(source)
    coverage = min(parsed_chars / max(source_chars, 1), 1.0)
    max_chars = lengths[-1] if lengths else 0
    p95 = lengths[min(len(lengths) - 1, math.ceil(len(lengths) * 0.95) - 1)] if lengths else 0
    anchored = sum(1 for item in clauses if item.source_locator or item.source_page)
    anchored_ratio = anchored / max(len(clauses), 1)
    warnings: list[str] = []
    score = 100

    if not clauses or parsed_chars == 0:
        warnings.append("未提取出有效正文")
        score -= 100
    empty_count = sum(1 for item in clauses if not _visible(item.content))
    if empty_count:
        warnings.append(f"存在 {empty_count} 个空条款")
        score -= 100
    if source.startswith("PK") or "[Content_Types].xml" in source[:500]:
        warnings.append("检测到 Office 压缩包二进制内容，文件类型解析错误")
        score -= 100
    if "\ufffd" in source_text:
        warnings.append("正文包含乱码替换符")
        score -= 25
    if source_chars >= 1000 and coverage < 0.75:
        warnings.append(f"正文覆盖率偏低（{coverage:.0%}）")
        score -= min(35, round((0.75 - coverage) * 100))
    if max_chars > 8000:
        warnings.append(f"存在超大条款（{max_chars} 字），疑似整篇未切分")
        score -= 40
    elif max_chars > 3000:
        warnings.append(f"存在偏大条款（{max_chars} 字）")
        score -= 35
    if source_chars > 3000 and len(clauses) <= 1:
        warnings.append("长文档仅形成一个条款")
        score -= 50
    if clauses and anchored_ratio < 0.8:
        warnings.append(f"来源锚点覆盖不足（{anchored_ratio:.0%}）")
        score -= 10
    if filename.lower().endswith((".xlsx", ".xls")) and not any(c.block_type == "table_row" for c in clauses):
        warnings.append("表格未按行结构化")
        score -= 50

    score = max(0, min(100, score))
    return ParseQualityReport(
        score=score, passed=score >= minimum_score and not any("二进制" in item for item in warnings),
        backend=backend, clause_count=len(clauses), source_chars=source_chars,
        parsed_chars=parsed_chars, coverage=round(coverage, 4), max_clause_chars=max_chars,
        p95_clause_chars=p95, anchored_ratio=round(anchored_ratio, 4), warnings=warnings,
    )
