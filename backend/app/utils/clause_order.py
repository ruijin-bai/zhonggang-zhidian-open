"""Stable source-order sorting for regulation clauses."""
from __future__ import annotations

import re
from typing import Iterable, TypeVar


_T = TypeVar("_T")
_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_SOURCE_INDEX_RE = re.compile(r"^(?:unit|clause|paragraph|row):(\d+)$", re.I)
_HEADING_RE = re.compile(r"^第([零〇一二两三四五六七八九十百千万\d]+)([编篇章节条款项目段行])")
_ITEM_RE = re.compile(r"^[（(]?([零〇一二两三四五六七八九十百千万\d]+)[）)、.]?")
_CONTINUATION_RE = re.compile(r"[（(]续\s*(\d+)[）)]")
_FAMILY_RANK = {"编": 0, "篇": 0, "章": 1, "节": 2, "条": 3, "款": 4,
                "项": 5, "目": 6, "段": 7, "行": 8}


def chinese_number(value: str) -> int | None:
    """Convert common Chinese or Arabic heading numerals to an integer."""
    text = (value or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if all(char in _CN_DIGITS for char in text):
        return int("".join(str(_CN_DIGITS[char]) for char in text))
    if any(char not in _CN_DIGITS and char not in _CN_UNITS for char in text):
        return None

    total = section = number = 0
    for char in text:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
            continue
        unit = _CN_UNITS[char]
        if unit == 10000:
            total += (section + number) * unit
            section = number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return total + section + number


def clause_order_key(clause: object) -> tuple:
    """Return document order, falling back to a natural clause-number order."""
    source_locator = str(getattr(clause, "source_locator", "") or "").strip()
    source_match = _SOURCE_INDEX_RE.match(source_locator)
    if source_match:
        return (0, int(source_match.group(1)), 0, 0, "")

    label = str(getattr(clause, "clause_no", "") or "").strip()
    heading_match = _HEADING_RE.match(label)
    if heading_match:
        number = chinese_number(heading_match.group(1))
        continuation = _CONTINUATION_RE.search(label)
        if number is not None:
            return (
                1,
                _FAMILY_RANK[heading_match.group(2)],
                number,
                int(continuation.group(1)) if continuation else 0,
                label,
            )

    item_match = _ITEM_RE.match(label)
    if item_match:
        number = chinese_number(item_match.group(1))
        if number is not None:
            return (2, number, 0, 0, label)

    source_page = getattr(clause, "source_page", None)
    if isinstance(source_page, int):
        return (3, source_page, 0, 0, label)
    return (4, 0, 0, 0, label)


def sort_clauses(clauses: Iterable[_T]) -> list[_T]:
    """Return a new list in stable, human-readable document order."""
    return sorted(clauses, key=clause_order_key)
