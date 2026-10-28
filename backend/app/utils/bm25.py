"""Okapi BM25 lexical retrieval for Chinese制度 text.

Replaces the naive query-hit overlap in ``keyword_score`` with a proper
term-weighting scheme:

* IDF (inverse document frequency) down-weights ubiquitous tokens
  (的/和/及/应当/规定) so they no longer drown out the rare, decisive terms;
* length normalisation keeps long clauses from ranking high purely by size.

The corpus statistics are computed over the *permission-filtered* clause set
at query time, which keeps the implementation storage-agnostic (no extra index
table) and correct for the RBAC-visible subset actually being searched.
"""
from __future__ import annotations

import math

from app.utils.text import tokenize

_K1 = 1.5
_B = 0.75


def build_corpus_stats(documents: list[str]) -> tuple[dict[str, float], float]:
    """Return (idf, avgdl) over the given document set.

    ``documents`` are the indexable text blobs (clause_no + content + tags).
    """
    doc_freq: dict[str, int] = {}
    doc_lens: list[int] = []
    for doc in documents:
        toks = tokenize(doc)
        doc_lens.append(len(toks))
        for t in set(toks):
            doc_freq[t] = doc_freq.get(t, 0) + 1
    n = max(1, len(documents))
    avgdl = (sum(doc_lens) / n) if doc_lens else 1.0
    idf: dict[str, float] = {}
    for t, df in doc_freq.items():
        idf[t] = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
    return idf, avgdl


def bm25_score(query: str, doc: str, idf: dict[str, float], avgdl: float) -> float:
    """Okapi BM25 score of ``doc`` against ``query`` given corpus IDF stats."""
    q_terms = set(tokenize(query))
    if not q_terms:
        return 0.0
    d_tokens = tokenize(doc)
    dl = len(d_tokens)
    tf: dict[str, int] = {}
    for t in d_tokens:
        tf[t] = tf.get(t, 0) + 1
    score = 0.0
    for t in q_terms:
        f = tf.get(t, 0)
        if f == 0:
            continue
        idf_t = idf.get(t, 0.0)
        denom = f + _K1 * (1.0 - _B + _B * (dl / avgdl))
        score += idf_t * (f * (_K1 + 1.0)) / denom
    return score
