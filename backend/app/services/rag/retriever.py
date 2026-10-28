"""Hybrid retriever: dense vector + BM25 lexical, fused with RRF (Reciprocal
Rank Fusion), with RBAC injection and metadata pre-filtering.

Two execution paths:
  * pgvector (production): SQL ``cosine_distance`` ordering with the permission
    predicate pushed into the WHERE clause.
  * memory / sqlite fallback: clauses are loaded (permission-filtered) and scored
    in Python — dense cosine similarity + Okapi BM25, fused by RRF ranking so the
    two heterogeneous signals (semantic vs. exact-term) never fight over raw
    score magnitudes.

Metadata pre-filtering: ``domain`` (regulation business domain) is pushed into
the SQL predicate before scoring; effective/expiry date already filters stale
or not-yet-effective files.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.adapters.embedding.factory import get_embedding_adapter
from app.adapters.llm.factory import get_llm_adapter
from app.adapters.reranker.factory import get_reranker_adapter
from app.core.config import get_settings
from app.core.exceptions import EmbeddingError
from app.db.models.clause import Clause
from app.db.models.regulation import RegulationFile
from app.db.models.asset import (
    AssetDocument,
    AssetVersion,
    AssetVersionDocument,
    ContentNode,
    DocumentParseRun,
    KnowledgeAsset,
    RetrievalEmbedding,
    RetrievalUnit,
    RetrievalUnitSource,
)
from app.services.assets.retrieval_index import (
    active_embedding_spec,
    eligible_unit_predicates,
)
from app.services.permission.rbac import build_asset_filter, build_filter
from app.utils.bm25 import bm25_score, build_corpus_stats

_SETTINGS = get_settings()

_RRF_K = 60  # RRF smoothing constant; larger => less sensitive to rank gaps.

# Deterministic business-vocabulary expansion. These are制度名称口径, not
# answers or approval rules: they only help colloquial questions reach the
# right source family before reranking.
_TOPIC_EXPANSIONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("加班", "调休", "考勤", "迟到", "早退", "休假", "年休"), "员工考勤休假"),
    (("处分", "处罚", "违纪", "违规"), "员工违规违纪处理"),
    (("实施策划", "境外项目"), "境外项目实施"),
    (("退出", "离职", "工作交接"), "员工退出"),
    (("借调",), "借调人员"),
    (("安全生产费",), "安全生产费用"),
    (("企业年金",), "企业年金"),
    (("绩效",), "绩效考核"),
    (("培训",), "员工教育培训"),
    (("补充医疗",), "补充医疗保险"),
    (("工资", "薪酬", "基本工资", "岗位基薪", "薪资", "待遇"), "薪酬"),
)


@dataclass
class RetrievedClause:
    clause: Clause
    file: RegulationFile
    score: float  # 0..1 fused relevance
    source_kind: str = "legacy_clause"
    source_metadata: dict = field(default_factory=dict)


@dataclass
class _MemoryVectorSnapshot:
    signature: tuple
    dimension: int
    clause_ids: tuple[str, ...]
    id_to_position: dict[str, int]
    normalized_matrix: np.ndarray
    index_blobs: dict[str, str]
    file_titles: dict[str, str]


_MEMORY_VECTOR_SNAPSHOT: _MemoryVectorSnapshot | None = None
_MEMORY_VECTOR_LOCK = asyncio.Lock()


@dataclass
class _CompoundVectorSnapshot:
    signature: tuple
    model_key: str
    dimension: int
    unit_ids: tuple[str, ...]
    id_to_position: dict[str, int]
    normalized_matrix: np.ndarray
    index_blobs: dict[str, str]
    asset_titles: dict[str, str]


_COMPOUND_VECTOR_SNAPSHOT: _CompoundVectorSnapshot | None = None
_COMPOUND_VECTOR_LOCK = asyncio.Lock()


async def _memory_vector_signature(session: AsyncSession) -> tuple:
    database_url = session.get_bind().url
    # Read only narrow covering indexes. Tying invalidation to the whole SQLite
    # file caused QA/audit writes to rebuild 14,119x4096 vectors unnecessarily.
    # Clause/regulation count + timestamps + edge IDs change only when retrieval
    # source data changes; ingestion also resets the process cache explicitly.
    count, newest, first_id, last_id = (await session.execute(
        select(
            func.count(Clause.clause_id),
            func.max(Clause.updated_at),
            func.min(Clause.clause_id),
            func.max(Clause.clause_id),
        ).where(Clause.status == "current", Clause.embedding.isnot(None))
    )).one()
    file_count, newest_file, first_file, last_file = (await session.execute(
        select(
            func.count(RegulationFile.file_id),
            func.max(RegulationFile.updated_at),
            func.min(RegulationFile.file_id),
            func.max(RegulationFile.file_id),
        ).where(RegulationFile.status == "current")
    )).one()
    return (
        str(database_url), int(count), newest, first_id, last_id,
        int(file_count), newest_file, first_file, last_file,
    )


def reset_memory_vector_cache() -> None:
    """Drop the process-local SQLite vector matrix after ingestion/config changes."""
    global _MEMORY_VECTOR_SNAPSHOT
    _MEMORY_VECTOR_SNAPSHOT = None


def reset_compound_vector_cache() -> None:
    """Drop the process-local V2 vector and lexical snapshot."""
    global _COMPOUND_VECTOR_SNAPSHOT
    _COMPOUND_VECTOR_SNAPSHOT = None


async def _compound_vector_signature(session: AsyncSession, model_key: str) -> tuple:
    count, newest, first_id, last_id = (await session.execute(
        select(
            func.count(RetrievalEmbedding.embedding_id),
            func.max(RetrievalEmbedding.updated_at),
            func.min(RetrievalEmbedding.unit_id),
            func.max(RetrievalEmbedding.unit_id),
        ).where(
            RetrievalEmbedding.model_key == model_key,
            RetrievalEmbedding.status == "ready",
            RetrievalEmbedding.vector.isnot(None),
        )
    )).one()
    unit_count, unit_newest = (await session.execute(
        select(func.count(RetrievalUnit.unit_id), func.max(RetrievalUnit.updated_at)).where(
            RetrievalUnit.status == "verified"
        )
    )).one()
    return (str(session.get_bind().url), model_key, int(count), newest, first_id, last_id, int(unit_count), unit_newest)


async def warm_compound_vector_cache(
    session: AsyncSession,
    model_key: str,
    expected_dim: int,
) -> _CompoundVectorSnapshot:
    """Cache V2 vectors and lexical text; SQL gates visibility per request."""
    global _COMPOUND_VECTOR_SNAPSHOT
    signature = await _compound_vector_signature(session, model_key)
    cached = _COMPOUND_VECTOR_SNAPSHOT
    if cached is not None and cached.signature == signature and cached.dimension == expected_dim:
        return cached
    async with _COMPOUND_VECTOR_LOCK:
        signature = await _compound_vector_signature(session, model_key)
        cached = _COMPOUND_VECTOR_SNAPSHOT
        if cached is not None and cached.signature == signature and cached.dimension == expected_dim:
            return cached
        vector_rows = list((await session.execute(
            select(RetrievalEmbedding.unit_id, RetrievalEmbedding.vector).where(
                RetrievalEmbedding.model_key == model_key,
                RetrievalEmbedding.status == "ready",
                RetrievalEmbedding.vector.isnot(None),
            ).order_by(RetrievalEmbedding.unit_id)
        )).all())
        valid = [(unit_id, vector) for unit_id, vector in vector_rows if len(vector or []) == expected_dim]
        unit_ids = tuple(unit_id for unit_id, _ in valid)
        if valid:
            matrix = np.asarray([vector for _, vector in valid], dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix /= np.maximum(norms, np.finfo(np.float32).eps)
        else:
            matrix = np.empty((0, expected_dim), dtype=np.float32)

        lexical_rows = list((await session.execute(
            select(
                RetrievalUnit.unit_id,
                RetrievalUnit.title,
                RetrievalUnit.text,
                KnowledgeAsset.title,
                AssetDocument.title,
                AssetVersionDocument.role,
            )
            .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
            .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
            .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
            .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
            .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
            .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
            .join(
                AssetVersionDocument,
                (AssetVersionDocument.version_id == AssetVersion.version_id)
                & (AssetVersionDocument.document_id == ContentNode.document_id),
            )
            .where(*eligible_unit_predicates())
        )).all())
        index_blobs: dict[str, str] = {}
        asset_titles: dict[str, str] = {}
        for unit_id, unit_title, unit_text, asset_title, document_title, role in lexical_rows:
            index_blobs.setdefault(
                unit_id,
                f"{asset_title or ''} {asset_title or ''} {document_title or ''} {role or ''} "
                f"{unit_title or ''} {unit_text or ''}",
            )
            asset_titles.setdefault(unit_id, asset_title or "")
        _COMPOUND_VECTOR_SNAPSHOT = _CompoundVectorSnapshot(
            signature=signature,
            model_key=model_key,
            dimension=expected_dim,
            unit_ids=unit_ids,
            id_to_position={unit_id: index for index, unit_id in enumerate(unit_ids)},
            normalized_matrix=matrix,
            index_blobs=index_blobs,
            asset_titles=asset_titles,
        )
        return _COMPOUND_VECTOR_SNAPSHOT


async def warm_memory_vector_cache(
    session: AsyncSession,
    expected_dim: int,
) -> _MemoryVectorSnapshot:
    """Load current vectors once and retain a normalized float32 matrix.

    SQLite persists vectors as JSON for portability. Parsing 4096 floats for
    every clause on every query is prohibitively slow, while PostgreSQL uses
    pgvector directly and never enters this path. The lightweight signature
    invalidates the snapshot when clauses are added, replaced or re-embedded.
    """
    global _MEMORY_VECTOR_SNAPSHOT
    signature = await _memory_vector_signature(session)
    cached = _MEMORY_VECTOR_SNAPSHOT
    if cached is not None and cached.signature == signature and cached.dimension == expected_dim:
        return cached

    async with _MEMORY_VECTOR_LOCK:
        cached = _MEMORY_VECTOR_SNAPSHOT
        signature = await _memory_vector_signature(session)
        if cached is not None and cached.signature == signature and cached.dimension == expected_dim:
            return cached

        vector_rows = list((await session.execute(
            select(Clause.clause_id, Clause.embedding).where(
                Clause.status == "current",
                Clause.embedding.isnot(None),
            ).order_by(Clause.clause_id)
        )).all())
        valid = [(clause_id, vector) for clause_id, vector in vector_rows if len(vector) == expected_dim]
        clause_ids = tuple(clause_id for clause_id, _ in valid)
        if valid:
            matrix = np.asarray([vector for _, vector in valid], dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            matrix /= np.maximum(norms, np.finfo(np.float32).eps)
        else:
            matrix = np.empty((0, expected_dim), dtype=np.float32)
        lexical_rows = list((await session.execute(
            select(
                Clause.clause_id,
                Clause.clause_no,
                Clause.content,
                Clause.scenario_tags,
                RegulationFile.title,
            )
            .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
            .where(Clause.status == "current", RegulationFile.status == "current")
        )).all())
        index_blobs: dict[str, str] = {}
        file_titles: dict[str, str] = {}
        for clause_id, clause_no, content, scenario_tags, title in lexical_rows:
            tags = " ".join(scenario_tags or [])
            file_title = title or ""
            index_blobs[clause_id] = (
                f"{file_title} {file_title} {clause_no or ''} {content or ''} {tags}"
            )
            file_titles[clause_id] = file_title
        _MEMORY_VECTOR_SNAPSHOT = _MemoryVectorSnapshot(
            signature=signature,
            dimension=expected_dim,
            clause_ids=clause_ids,
            id_to_position={clause_id: index for index, clause_id in enumerate(clause_ids)},
            normalized_matrix=matrix,
            index_blobs=index_blobs,
            file_titles=file_titles,
        )
        return _MEMORY_VECTOR_SNAPSHOT


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    # A switched embedding provider can leave historic vectors at a different
    # dimension. Never turn that operational mismatch into a 500 for users.
    if va.shape != vb.shape:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _minmax(values: dict[str, float], ids: list[str]) -> dict[str, float]:
    """Min-max normalise a score map to [0,1]; flat maps collapse to 0.5."""
    vals = [values[i] for i in ids]
    mn, mx = min(vals), max(vals)
    if mx - mn < 1e-9:
        return {i: 0.5 for i in ids}
    return {i: (values[i] - mn) / (mx - mn) for i in ids}


def _fuse(vec_scores: dict[str, float], bm_scores: dict[str, float]) -> tuple[list[str], dict[str, float]]:
    """RRF rank fusion + a stable 0..1 score.

    Ordering uses RRF (robust to heterogeneous score distributions); the final
    ``score`` is a min-max-normalised weighted blend (0.6 dense + 0.4 BM25) so
    downstream confidence/`min_score` filtering stays on a stable 0..1 scale.
    """
    ids = list(vec_scores.keys())
    vn = _minmax(vec_scores, ids)
    bn = _minmax(bm_scores, ids)
    weighted = {i: 0.6 * vn[i] + 0.4 * bn[i] for i in ids}

    vec_order = sorted(ids, key=lambda i: -vec_scores[i])
    bm_order = sorted(ids, key=lambda i: -bm_scores[i])
    vec_rank = {cid: r + 1 for r, cid in enumerate(vec_order)}
    bm_rank = {cid: r + 1 for r, cid in enumerate(bm_order)}
    rrf = {i: 1.0 / (_RRF_K + vec_rank[i]) + 1.0 / (_RRF_K + bm_rank[i]) for i in ids}
    # RRF may tie when one document ranks first in dense and another first in
    # lexical retrieval. Use the normalised relevance blend as a deterministic
    # tie-breaker so exact codes/names are not lost to insertion order.
    order = sorted(ids, key=lambda i: (-rrf[i], -weighted[i], i))
    return order, weighted


def _index_blob(clause: Clause, file: RegulationFile | None = None) -> str:
    """Lexical index text: title + clause number + content + scenario tags."""
    tags = " ".join(clause.scenario_tags) if clause.scenario_tags else ""
    title = file.title if file is not None else ""
    # Repeat the title once: an exact制度名称 is a strong business signal, but
    # clause text still remains the majority of the BM25 document.
    return f"{title} {title} {clause.clause_no or ''} {clause.content or ''} {tags}"


def _query_terms(question: str) -> list[str]:
    """Extract a bounded set of safe SQL lexical terms, including Chinese bigrams."""
    expansions = _topic_hints(question)
    raw_terms = re.findall(r"[A-Za-z0-9]{2,}|[一-鿿]{2,}", question or "")
    terms: list[str] = list(expansions)
    for raw in raw_terms:
        if raw not in terms:
            terms.append(raw)
        if len(raw) > 4 and re.search(r"[一-鿿]", raw):
            terms.extend(raw[i:i + 2] for i in range(len(raw) - 1))
    return list(dict.fromkeys(term for term in terms if term.strip()))[:16]


def _topic_hints(question: str) -> list[str]:
    hints = [hint for triggers, hint in _TOPIC_EXPANSIONS if any(word in question for word in triggers)]
    # M 级属于领导/管理职务职级语境；仅在询问晋升或任职时间时路由到
    # 领导人员制度，避免把薪酬问题错误导向任职资格。
    if re.search(r"(?i)(?:^|[^a-z])m\s*\d", question or "") and any(
        word in (question or "") for word in ("到", "升", "晋升", "任职", "时间", "年限", "多久")
    ):
        hints.append("领导人员")
    if re.search(r"(?i)(?:^|[^a-z])p(?:m)?\s*\d", question or ""):
        hints.append("职业发展")
    return list(dict.fromkeys(hints))


def _expanded_question(question: str) -> str:
    hints = _topic_hints(question)
    return " ".join([question, *hints])


def _title_topic_score(question: str, title: str) -> float:
    """Return a deterministic source-family match without inferring an answer."""
    if title and title.strip() and title.strip().lower() in (question or "").lower():
        return 1.0
    hints = _topic_hints(question)
    return 1.0 if any(hint in (title or "") for hint in hints) else 0.0


class RetrieverService:
    """Hybrid retrieval with permission filtering (architecture §6 T07)."""

    def __init__(self) -> None:
        self.embed = get_embedding_adapter()
        self.llm = get_llm_adapter()
        self.reranker = get_reranker_adapter()

    async def retrieve(
        self,
        session: AsyncSession,
        user,
        permissions,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
        domain: str | None = None,
    ) -> list[RetrievedClause]:
        top_k = top_k or _SETTINGS.RETRIEVE_TOP_K
        min_score = min_score if min_score is not None else _SETTINGS.RETRIEVE_MIN_SCORE

        try:
            # Adapter contract is synchronous for ingestion compatibility;
            # never block FastAPI's event loop on the external HTTP call.
            qvec = (await asyncio.to_thread(self.embed.embed, [question]))[0]
        except EmbeddingError:
            # Vector providers are an external dependency. Preserve RBAC and
            # date/domain predicates, then fall back to bounded SQL + BM25 so a
            # temporary provider outage does not take the knowledge base down.
            qvec = []
        candidate_limit = min(top_k * 2, _SETTINGS.RETRIEVE_PREFILTER)
        compound = await self._retrieve_compound(
            session, user, permissions, question, qvec, candidate_limit, min_score, domain
        )
        perm_filter = build_filter(user, permissions, Clause.secret_level)

        base = (
            select(Clause, RegulationFile)
            .join(RegulationFile, Clause.file_id == RegulationFile.file_id)
            .where(
                Clause.status == "current",
                RegulationFile.status == "current",
                or_(RegulationFile.effective_date.is_(None), RegulationFile.effective_date <= date.today()),
                or_(RegulationFile.expiry_date.is_(None), RegulationFile.expiry_date >= date.today()),
                perm_filter,
            )
        )
        if domain and domain != "*":
            base = base.where(or_(RegulationFile.domain == "*", RegulationFile.domain == domain))

        if not qvec:
            legacy = await self._retrieve_lexical(session, base, question, candidate_limit, min_score)
        else:
            dense_base = base.where(Clause.embedding.isnot(None))
            if _SETTINGS.is_sqlite or _SETTINGS.VECTOR_BACKEND == "memory":
                legacy = await self._retrieve_memory(session, dense_base, qvec, question, candidate_limit, min_score)
            else:
                legacy = await self._retrieve_pg_hybrid(session, dense_base, qvec, question, candidate_limit, min_score)
        return self._merge_sources(compound, legacy, top_k)

    @staticmethod
    def _merge_sources(
        compound: list[RetrievedClause], legacy: list[RetrievedClause], top_k: int
    ) -> list[RetrievedClause]:
        """Prefer source-faithful V2 units while retaining a bounded V1 safety net."""
        merged: dict[tuple, RetrievedClause] = {}
        for candidate in [*compound, *legacy]:
            # Migrated V1/V2 copies can differ only in PDF whitespace. Collapse
            # them inside the same source version; identical wording in other
            # regulations or versions remains independent evidence.
            identity = candidate.source_metadata.get("legacy_file_id") or candidate.file.file_id
            fingerprint = (identity, candidate.file.version, re.sub(r"\s+", "", candidate.clause.content or ""))
            current = merged.get(fingerprint)
            if current is None or (candidate.source_kind == "compound_unit" and current.source_kind != "compound_unit") or (candidate.source_kind == current.source_kind and candidate.score > current.score):
                merged[fingerprint] = candidate
        ranked = sorted(
            merged.values(),
            key=lambda item: (-item.score, 0 if item.source_kind == "compound_unit" else 1),
        )
        return ranked[:top_k]

    async def _retrieve_compound(
        self,
        session: AsyncSession,
        user,
        permissions,
        question: str,
        qvec: list[float],
        top_k: int,
        min_score: float,
        domain: str | None,
    ) -> list[RetrievedClause]:
        """Retrieve governed compound-asset units with pre-vector RBAC gates."""
        visibility = build_asset_filter(
            user,
            permissions,
            secret_level=KnowledgeAsset.secret_level,
            content_secret_level=RetrievalUnit.secret_level,
            org_path=KnowledgeAsset.org_path,
            domain=KnowledgeAsset.domain,
        )
        visible_stmt = (
            select(RetrievalUnit.unit_id)
            .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
            .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
            .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
            .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
            .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
            .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
            .join(
                AssetVersionDocument,
                (AssetVersionDocument.version_id == AssetVersion.version_id)
                & (AssetVersionDocument.document_id == ContentNode.document_id),
            )
            .where(*eligible_unit_predicates(), visibility, build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level, org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain, content_secret_level=AssetDocument.secret_level))
        )
        if domain and domain != "*":
            visible_stmt = visible_stmt.where(
                or_(KnowledgeAsset.domain == "*", KnowledgeAsset.domain == domain)
            )
        visible_ids = list(dict.fromkeys((await session.execute(visible_stmt)).scalars()))
        if not visible_ids:
            return []

        spec = active_embedding_spec()
        expected_dim = len(qvec) if qvec else spec.dimension
        snapshot = await warm_compound_vector_cache(session, spec.model_key, expected_dim)
        candidate_ids: dict[str, None] = {}
        vector_scores: dict[str, float] = {}
        all_scores: np.ndarray | None = None
        visible_positions = [
            (unit_id, snapshot.id_to_position[unit_id])
            for unit_id in visible_ids
            if unit_id in snapshot.id_to_position
        ]
        if qvec and visible_positions and snapshot.normalized_matrix.size:
            qv = np.asarray(qvec, dtype=np.float32)
            qv /= max(float(np.linalg.norm(qv)), float(np.finfo(np.float32).eps))
            all_scores = snapshot.normalized_matrix @ qv
            ranked_positions = sorted(
                visible_positions,
                key=lambda item: -float(all_scores[item[1]]),
            )[: _SETTINGS.RETRIEVE_PREFILTER]
            candidate_ids.update({unit_id: None for unit_id, _ in ranked_positions})

        terms = [term.lower() for term in _query_terms(question)]
        hints = [hint.lower() for hint in _topic_hints(question)]
        question_lower = question.lower()
        for unit_id in visible_ids:
            title = snapshot.asset_titles.get(unit_id, "").lower()
            if title and (title in question_lower or any(hint in title for hint in hints)):
                candidate_ids[unit_id] = None
        lexical_added = 0
        for unit_id in visible_ids:
            blob = snapshot.index_blobs.get(unit_id, "").lower()
            if terms and any(term in blob for term in terms):
                if unit_id not in candidate_ids:
                    candidate_ids[unit_id] = None
                    lexical_added += 1
                if lexical_added >= _SETTINGS.RETRIEVE_LEXICAL_CANDIDATES:
                    break
        if not candidate_ids:
            candidate_ids.update({unit_id: None for unit_id in visible_ids[: _SETTINGS.RETRIEVE_PREFILTER]})

        rows = await self._hydrate_compound_rows(session, list(candidate_ids), spec.model_key, user, permissions)
        if all_scores is not None:
            for clause, _file in rows:
                position = snapshot.id_to_position.get(clause.clause_id)
                if position is not None:
                    vector_scores[clause.clause_id] = float(all_scores[position])
        return self._rank_candidates(
            rows,
            [],
            question,
            top_k,
            min_score,
            vector_scores=vector_scores,
        )

    async def _hydrate_compound_rows(
        self, session: AsyncSession, unit_ids: list[str], model_key: str, user, permissions
    ) -> list[tuple[Clause, RegulationFile]]:
        if not unit_ids:
            return []
        stmt = (
            select(
                RetrievalUnit,
                AssetVersion,
                KnowledgeAsset,
                AssetDocument,
                ContentNode,
                AssetVersionDocument,
            )
            .join(AssetVersion, AssetVersion.version_id == RetrievalUnit.version_id)
            .join(KnowledgeAsset, KnowledgeAsset.asset_id == AssetVersion.asset_id)
            .join(RetrievalUnitSource, RetrievalUnitSource.unit_id == RetrievalUnit.unit_id)
            .join(ContentNode, ContentNode.node_id == RetrievalUnitSource.node_id)
            .join(AssetDocument, AssetDocument.document_id == ContentNode.document_id)
            .join(DocumentParseRun, DocumentParseRun.parse_run_id == ContentNode.parse_run_id)
            .join(
                AssetVersionDocument,
                (AssetVersionDocument.version_id == AssetVersion.version_id)
                & (AssetVersionDocument.document_id == ContentNode.document_id),
            )
            .where(RetrievalUnit.unit_id.in_(unit_ids), *eligible_unit_predicates(), build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level, org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain, content_secret_level=RetrievalUnit.secret_level), build_asset_filter(user, permissions, secret_level=KnowledgeAsset.secret_level, org_path=KnowledgeAsset.org_path, domain=KnowledgeAsset.domain, content_secret_level=AssetDocument.secret_level))
        )
        hydrated: dict[str, tuple[Clause, RegulationFile]] = {}
        for unit, version, asset, document, node, link in (await session.execute(stmt)).all():
            if unit.unit_id in hydrated:
                continue
            label = unit.title or node.label or node.title or node.source_locator or unit.unit_type
            clause = Clause(
                clause_id=unit.unit_id,
                file_id=asset.asset_id,
                chapter=node.title or None,
                clause_no=label[:64],
                content=unit.text,
                source_page=node.source_page,
                source_locator=node.source_locator,
                content_hash=unit.content_hash,
                secret_level=unit.secret_level,
                scenario_tags=[document.title, link.role, unit.unit_type],
                status="current",
            )
            clause._source_kind = "compound_unit"
            clause._source_metadata = {
                "unit_id": unit.unit_id,
                "asset_id": asset.asset_id,
                "legacy_file_id": version.legacy_file_id,
                "version_id": version.version_id,
                "document_id": document.document_id,
                "node_id": node.node_id,
                "document_role": link.role,
                "source_locator": node.source_locator,
                "sheet_name": node.sheet_name,
                "cell_range": node.cell_range,
            }
            from app.services.assets.publication import source_verification as asset_verification
            file = RegulationFile(
                file_id=asset.asset_id,
                regulation_code=version.issue_no or asset.business_code,
                title=asset.title,
                source=document.title or document.filename,
                version=version.version_label,
                status="current",
                effective_date=version.effective_date,
                expiry_date=version.expiry_date,
                reviewed_by=version.reviewed_by,
                reviewed_at=version.reviewed_at,
                review_note=version.review_note,
                source_confirmation=(version.version_metadata or {}).get("source_confirmation", {}) if asset_verification(asset, version) == "maintainer" else {},
                owner_org=asset.owner_org,
                org_path=asset.org_path,
                secret_level=asset.secret_level,
                domain=asset.domain,
                lang=asset.lang,
            )
            file.source_version_id = version.version_id
            hydrated[unit.unit_id] = (clause, file)
        return list(hydrated.values())

    async def _retrieve_lexical(
        self,
        session: AsyncSession,
        base,
        question: str,
        top_k: int,
        min_score: float,
    ) -> list[RetrievedClause]:
        """Permission-filtered lexical fallback used only when embedding fails."""
        terms = _query_terms(question)
        if not terms:
            return []
        exact_rows: list[tuple[Clause, RegulationFile]] = []
        hints = _topic_hints(question)
        if hints:
            title_predicates = [RegulationFile.title.ilike(f"%{hint}%") for hint in hints]
            exact_rows = list((await session.execute(base.where(or_(*title_predicates)).limit(50))).all())
        predicates = []
        for term in terms:
            escaped = term.replace("%", "\\%").replace("_", "\\_")
            predicates.extend([
                Clause.content.ilike(f"%{escaped}%", escape="\\"),
                Clause.clause_no.ilike(f"%{escaped}%", escape="\\"),
                RegulationFile.title.ilike(f"%{escaped}%", escape="\\"),
            ])
        stmt = base.where(or_(*predicates)).limit(_SETTINGS.RETRIEVE_LEXICAL_CANDIDATES)
        rows = {clause.clause_id: (clause, file) for clause, file in exact_rows}
        for clause, file in (await session.execute(stmt)).all():
            rows[clause.clause_id] = (clause, file)
        return self._rank_candidates(list(rows.values()), [], question, top_k, min_score)

    async def _retrieve_pg_hybrid(
        self,
        session: AsyncSession,
        base,
        qvec: list[float],
        question: str,
        top_k: int,
        min_score: float,
    ) -> list[RetrievedClause]:
        """Production path with the same dense + BM25 + RRF semantics as SQLite.

        pgvector supplies the dense candidate set. A bounded exact-term query
        adds clauses that vector similarity may miss (codes, amounts, names),
        then both sets are fused in application code. This prevents production
        from silently degrading to vector-only retrieval.
        """
        distance_expr = Clause.embedding.cosine_distance(qvec)
        vector_stmt = (
            base.add_columns(distance_expr.label("dist"))
            .order_by(distance_expr)
            .limit(_SETTINGS.RETRIEVE_PREFILTER)
        )
        vector_rows = list((await session.execute(vector_stmt)).all())
        merged: dict[str, tuple[Clause, RegulationFile]] = {
            clause.clause_id: (clause, file) for clause, file, _dist in vector_rows
        }

        terms = _query_terms(question)
        hints = _topic_hints(question)
        title_terms = [term for term in terms if len(term) >= 4]
        if title_terms:
            exact_source_stmt = base.where(RegulationFile.title.in_(title_terms)).limit(
                _SETTINGS.RETRIEVE_LEXICAL_CANDIDATES
            )
            for clause, file in (await session.execute(exact_source_stmt)).all():
                merged[clause.clause_id] = (clause, file)
        if hints:
            exact_title_stmt = base.where(
                or_(*[RegulationFile.title.ilike(f"%{hint}%") for hint in hints])
            ).limit(50)
            for clause, file in (await session.execute(exact_title_stmt)).all():
                merged[clause.clause_id] = (clause, file)
        if terms:
            lexical_predicates = []
            for term in terms:
                escaped = term.replace("%", "\\%").replace("_", "\\_")
                lexical_predicates.extend([
                    Clause.content.ilike(f"%{escaped}%", escape="\\"),
                    RegulationFile.title.ilike(f"%{escaped}%", escape="\\"),
                ])
            lexical_stmt = base.where(or_(*lexical_predicates)).limit(
                _SETTINGS.RETRIEVE_LEXICAL_CANDIDATES
            )
            for clause, file in (await session.execute(lexical_stmt)).all():
                merged[clause.clause_id] = (clause, file)

        return self._rank_candidates(list(merged.values()), qvec, question, top_k, min_score)

    def _rank_candidates(
        self,
        rows: list[tuple[Clause, RegulationFile]],
        qvec: list[float],
        question: str,
        top_k: int,
        min_score: float,
        vector_scores: dict[str, float] | None = None,
    ) -> list[RetrievedClause]:
        if not rows:
            return []
        lexical_question = _expanded_question(question)
        idf, avgdl = build_corpus_stats([_index_blob(clause, file) for clause, file in rows])
        vec_scores = (
            {clause.clause_id: vector_scores.get(clause.clause_id, 0.0) for clause, _ in rows}
            if vector_scores is not None
            else {clause.clause_id: _cosine(qvec, clause.embedding) for clause, _ in rows}
        )
        bm_scores = {
            clause.clause_id: bm25_score(lexical_question, _index_blob(clause, file), idf, avgdl)
            for clause, file in rows
        }
        ids = list(vec_scores)
        vector_compatible = any(vec_scores.values())
        if vector_compatible:
            order, weighted = _fuse(vec_scores, bm_scores)
        else:
            order = sorted(ids, key=lambda item: -bm_scores[item])
            weighted = _minmax(bm_scores, ids)
        by_id = {clause.clause_id: (clause, file) for clause, file in rows}
        base_rank = {clause_id: rank for rank, clause_id in enumerate(order)}
        topic_scores = {
            clause_id: _title_topic_score(question, by_id[clause_id][1].title)
            for clause_id in order
        }
        # Exact source-family matches precede semantic lookalikes. This only
        # routes retrieval; the cited clause and human-reviewed source remain
        # the basis of every answer.
        order = sorted(order, key=lambda clause_id: (-topic_scores[clause_id], base_rank[clause_id]))
        result: list[RetrievedClause] = []
        for clause_id in order:
            score = round(min(1.0, weighted[clause_id] + 0.25 * topic_scores[clause_id]), 4)
            if score < min_score:
                continue
            clause, file = by_id[clause_id]
            result.append(RetrievedClause(
                clause=clause,
                file=file,
                score=score,
                source_kind=getattr(clause, "_source_kind", "legacy_clause"),
                source_metadata=getattr(clause, "_source_metadata", {}),
            ))
            if len(result) >= top_k:
                break
        return result

    async def _retrieve_memory(
        self,
        session: AsyncSession,
        base,
        qvec: list[float],
        question: str,
        top_k: int,
        min_score: float,
    ) -> list[RetrievedClause]:
        # Query only IDs for the permission/date/domain gate. Fetching complete
        # ORM rows here would walk the 952 MB SQLite table before prefiltering.
        visible_ids = list(dict.fromkeys((await session.execute(
            base.with_only_columns(Clause.clause_id, maintain_column_froms=True)
        )).scalars()))
        if not visible_ids:
            return []

        snapshot = await warm_memory_vector_cache(session, len(qvec))
        visible_positions = [
            (clause_id, snapshot.id_to_position[clause_id])
            for clause_id in visible_ids
            if clause_id in snapshot.id_to_position
        ]
        vector_compatible = bool(visible_positions and snapshot.normalized_matrix.size)

        # 向量粗筛：numpy 矩阵运算一次性算全库余弦，取 top-N 候选池。
        # 中文分词是主要耗时，只对候选池（而非全库）算 BM25/IDF，检索 5s→亚秒级。
        prefilter = _SETTINGS.RETRIEVE_PREFILTER
        all_scores: np.ndarray | None = None
        candidate_ids: dict[str, None] = {}
        if vector_compatible:
            qv = np.asarray(qvec, dtype=np.float32)
            qv /= max(float(np.linalg.norm(qv)), float(np.finfo(np.float32).eps))
            all_scores = snapshot.normalized_matrix @ qv
            if len(visible_positions) > prefilter:
                visible_scores = np.asarray([
                    all_scores[position] for _, position in visible_positions
                ])
                top_indices = np.argsort(-visible_scores)[:prefilter]
                for local_index in top_indices:
                    clause_id, _position = visible_positions[int(local_index)]
                    candidate_ids[clause_id] = None
            else:
                candidate_ids.update({clause_id: None for clause_id, _ in visible_positions})

        # SQLite must have the same hybrid semantics as PostgreSQL: vector
        # prefiltering alone can discard an exact制度名称 before BM25 sees it.
        # The lexical text is also cached at startup; scan cheap Python strings,
        # then hydrate only the bounded candidate set from the ORM.
        terms = [term.lower() for term in _query_terms(question)]
        hints = [hint.lower() for hint in _topic_hints(question)]
        question_lower = question.lower()
        # Exact source names must never be lost because an unrelated vector
        # prefilter or an early lexical quota filled first. This is especially
        # important for long, similarly worded enterprise handbooks.
        for clause_id in visible_ids:
            title = snapshot.file_titles.get(clause_id, "").lower()
            if title and title in question_lower:
                candidate_ids[clause_id] = None
        if hints:
            for clause_id in visible_ids:
                title = snapshot.file_titles.get(clause_id, "").lower()
                if any(hint in title for hint in hints):
                    candidate_ids[clause_id] = None
        lexical_added = 0
        for clause_id in visible_ids:
            blob = snapshot.index_blobs.get(clause_id, "").lower()
            if terms and any(term in blob for term in terms):
                if clause_id not in candidate_ids:
                    candidate_ids[clause_id] = None
                    lexical_added += 1
                if lexical_added >= _SETTINGS.RETRIEVE_LEXICAL_CANDIDATES:
                    break
        if not candidate_ids:
            candidate_ids.update({clause_id: None for clause_id in visible_ids[:prefilter]})

        rows = list((await session.execute(
            base.where(Clause.clause_id.in_(list(candidate_ids))).options(defer(Clause.embedding))
        )).all())
        vector_scores: dict[str, float] = {}
        if all_scores is not None:
            for clause, _file in rows:
                position = snapshot.id_to_position.get(clause.clause_id)
                if position is not None:
                    vector_scores[clause.clause_id] = float(all_scores[position])
        return self._rank_candidates(
            rows, [], question, top_k, min_score,
            vector_scores=vector_scores,
        )

    async def rerank(
        self,
        question: str,
        candidates: list[RetrievedClause],
        top_k: int | None = None,
    ) -> list[RetrievedClause]:
        """Rerank hybrid-retrieval candidates (architecture §6 T07+).

        优先使用专门 reranker 模型；reranker 未配置/超时/返回异常时优雅降级回
        LLM 0-10 打分逻辑，两者都失败则保持原序——绝不让重排阻塞链路。
        """
        limit = top_k or _SETTINGS.RETRIEVE_TOP_K
        if not _SETTINGS.QA_RERANK_ENABLED or not candidates:
            return candidates[:limit]

        if self.reranker is not None:
            try:
                reordered = await self._rerank_with_model(question, candidates, limit)
                if reordered:
                    return reordered
            except Exception:  # noqa: BLE001
                # reranker 未配置/超时/异常 → 降级到 LLM 打分，不抛出、不阻塞。
                pass

        return await self._rerank_with_llm(question, candidates, limit)

    async def _rerank_with_model(
        self,
        question: str,
        candidates: list[RetrievedClause],
        top_k: int,
    ) -> list[RetrievedClause]:
        """专门 reranker 打分，保留可跨查询比较的绝对相关度。

        旧实现对每次查询做 min-max，导致最相关结果无论质量如何都变成 1.0，
        进而绕过低分自检和追问。现在 0..1 概率原样保留，logit 用 sigmoid
        映射，再与一小部分初检分融合，避免单模型抖动。
        """
        documents = [
            f"《{c.file.title}》{c.clause.clause_no}：{c.clause.content[:500]}"
            for c in candidates
        ]
        scored = await self.reranker.rerank(question, documents, top_n=top_k)
        if not scored:
            return []
        by_index = {i: c for i, c in enumerate(candidates)}

        out: list[RetrievedClause] = []
        for idx, raw_score in scored:
            if idx not in by_index:
                continue
            c = by_index[idx]
            calibrated = raw_score if 0.0 <= raw_score <= 1.0 else 1.0 / (1.0 + math.exp(-raw_score))
            combined = 0.75 * calibrated + 0.25 * c.score
            out.append(
                replace(c, score=round(max(0.0, min(1.0, combined)), 4))
            )
        if not out:
            return []
        out.sort(key=lambda x: x.score, reverse=True)
        return out[:top_k]

    async def _rerank_with_llm(
        self,
        question: str,
        candidates: list[RetrievedClause],
        top_k: int,
    ) -> list[RetrievedClause]:
        """LLM 0-10 打分重排（降级路径）；失败时保持原序。"""
        try:
            items = "\n".join(
                f"[{i}] 《{c.file.title}》{c.clause.clause_no}：{c.clause.content[:200]}"
                for i, c in enumerate(candidates)
            )
            prompt = (
                "你是企业制度检索的精排助手。请评估下列每条制度条款与用户问题的相关性，"
                "给出 0-10 的整数分（10 最相关）。只返回一个 JSON 数组，如 [8,3,5]，不要任何解释。\n"
                f"用户问题：{question}\n条款：\n{items}"
            )
            result = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                timeout=_SETTINGS.QA_RERANK_TIMEOUT,
                max_tokens=256,
                temperature=0.0,
            )
            scores = json.loads(result.content)
            reordered: list[RetrievedClause] = []
            for i, s in enumerate(scores):
                if i >= len(candidates):
                    break
                try:
                    new_score = max(0.0, min(1.0, float(s) / 10.0))
                except (TypeError, ValueError):
                    new_score = candidates[i].score
                reordered.append(
                    replace(candidates[i], score=round(new_score, 4))
                )
            reordered.sort(key=lambda x: x.score, reverse=True)
            return reordered[:top_k]
        except Exception:  # noqa: BLE001
            return candidates[:top_k]
