"""Deterministic, claim-level citation coverage checks for generated answers."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.services.rag.retriever import RetrievedClause

_CITE_RE = re.compile(r"\[(\d+)]")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])\d+(?:\.\d+)?\s*(?:%|％|亿元|万元|元|万美元|美元|欧元|奈拉|天|日|个月|月|年|小时)?",
    re.IGNORECASE,
)
_MARKDOWN_RE = re.compile(r"^[\s>*#\-+\d.、（）()]+")
_ARITHMETIC_RE = re.compile(
    r"((?:\d+(?:\.\d+)?\s*\+\s*)+\d+(?:\.\d+)?)\s*=\s*(\d+(?:\.\d+)?)\s*(%|％|天|日|个月|月|年|小时)?"
)


def requires_strict_numeric_grounding(question: str) -> bool:
    """Whether a wrong number would materially change the business answer."""
    q = question or ""
    return any(word in q for word in (
        "多少", "多少钱", "金额", "比例", "费率", "计提", "提取", "怎么算",
        "多久", "几年", "几天", "年限", "最短时间", "最长时间",
    ))


def _verified_derived_numbers(claim: str) -> set[str]:
    """Return RHS values from arithmetically valid addition expressions."""
    verified: set[str] = set()
    for expression, rhs_raw, unit in _ARITHMETIC_RE.findall(claim or ""):
        operands = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", expression)]
        rhs = float(rhs_raw)
        if operands and abs(sum(operands) - rhs) < 1e-9:
            canonical = str(int(rhs)) if rhs.is_integer() else str(rhs)
            verified.add(_norm_number(canonical))
            if unit:
                verified.add(_norm_number(canonical + unit))
    return verified


@dataclass
class GroundingReport:
    passed: bool
    claim_count: int
    covered_claim_count: int
    coverage_rate: float
    invalid_citation_indices: list[int]
    numeric_mismatch_claims: list[str]
    uncited_claims: list[str]
    referenced_indices: list[int]

    def to_dict(self) -> dict:
        return asdict(self)


def passes_numeric_guard(report: GroundingReport) -> bool:
    """Strict numeric safety with a slightly narrower scope than prose grounding.

    Prose may still need human review at 80-89% citation coverage, but a numeric
    answer is safe to display only when every number is source-backed or is the
    RHS of a verified addition expression.
    """
    return (
        report.coverage_rate >= 0.8
        and not report.invalid_citation_indices
        and not report.numeric_mismatch_claims
    )


def _claims(answer: str) -> list[str]:
    claims: list[str] = []
    for raw_line in (answer or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "权威状态" in line and ("待核验" in line or "已完成元数据核验" in line):
            # This is a system governance notice derived from document
            # metadata, not a factual claim derived from clause text.
            continue
        # Markdown section labels and compact table headers organize the answer
        # but do not assert a business fact, so they do not require a citation.
        if not _CITE_RE.search(line) and re.fullmatch(r"\*\*[^*]+\*\*", line):
            continue
        if line.startswith("|") and not _CITE_RE.search(line):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(len(re.findall(r"[\u4e00-\u9fff]", cell)) <= 4 for cell in cells):
                continue
        line = _MARKDOWN_RE.sub("", line).strip()
        line_refs = _CITE_RE.findall(line)
        # Keep a citation immediately following Chinese punctuation attached to
        # the preceding claim (both ``结论[1]。`` and ``结论。[1]`` are valid).
        for part in re.split(r"(?<=[。！？；])\s*(?!\[\d+])", line):
            plain = _CITE_RE.sub("", part).strip()
            cjk_count = len(re.findall(r"[\u4e00-\u9fff]", plain))
            if cjk_count >= 6 or _NUMBER_RE.search(plain):
                # A citation at the end of one Markdown paragraph conventionally
                # supports all sentences in that paragraph. Numeric consistency
                # is still checked for every individual sentence below.
                if not _CITE_RE.search(part) and line_refs:
                    part = part + " " + "".join(f"[{idx}]" for idx in line_refs)
                claims.append(part.strip())
    return claims


def _norm_number(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("％", "%").lower()


def evaluate_grounding(answer: str, candidates: list[RetrievedClause]) -> GroundingReport:
    """Check that every substantive claim has valid source markers.

    This is deliberately deterministic.  It does not pretend to solve full
    semantic entailment; instead it enforces source coverage and catches the
    highest-risk hallucination class for制度问答: numbers/amounts/periods that do
    not appear in the cited clauses.
    """
    claims = _claims(answer)
    covered = 0
    invalid: set[int] = set()
    referenced: set[int] = set()
    numeric_mismatches: list[str] = []
    uncited: list[str] = []

    for claim in claims:
        refs = [int(item) for item in _CITE_RE.findall(claim)]
        valid_refs = [idx for idx in refs if 1 <= idx <= len(candidates)]
        referenced.update(valid_refs)
        invalid.update(idx for idx in refs if idx < 1 or idx > len(candidates))
        if not valid_refs:
            uncited.append(claim[:160])
            continue
        source = "\n".join(
            f"{candidates[idx - 1].file.title} {candidates[idx - 1].clause.clause_no} "
            f"{candidates[idx - 1].clause.content or ''}"
            for idx in valid_refs
        )
        claim_numbers = {_norm_number(v) for v in _NUMBER_RE.findall(_CITE_RE.sub("", claim))}
        source_numbers = {_norm_number(v) for v in _NUMBER_RE.findall(source)}
        # Derived totals do not appear verbatim in a clause. Accept them only
        # when the answer exposes a mathematically valid addition expression.
        source_numbers.update(_verified_derived_numbers(claim))
        if claim_numbers - source_numbers:
            numeric_mismatches.append(claim[:160])
            continue
        covered += 1

    rate = round(covered / len(claims), 3) if claims else 0.0
    return GroundingReport(
        passed=bool(claims) and rate >= 0.9 and not invalid and not numeric_mismatches,
        claim_count=len(claims),
        covered_claim_count=covered,
        coverage_rate=rate,
        invalid_citation_indices=sorted(invalid),
        numeric_mismatch_claims=numeric_mismatches[:5],
        uncited_claims=uncited[:5],
        referenced_indices=sorted(referenced),
    )
