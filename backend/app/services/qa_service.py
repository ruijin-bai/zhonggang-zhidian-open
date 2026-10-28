"""QA orchestration (architecture §4.1 / §4.2).

Streaming-first pipeline: rewrite → retrieve → rerank → (optional dynamic
follow-up) → contradiction check → streaming generate → citations → confidence
→ persist. ``ask_stream`` is the core async generator yielding progress events;
``ask`` collects those events into the legacy synchronous payload for backward
compatibility. All LLM-augmented steps degrade gracefully on timeout/error.
"""
from __future__ import annotations

import asyncio
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import EmbeddingError, LLMTimeoutError
from app.db.models.qa import QACitation, QASession
from app.services.audit import record_audit
from app.services.rag.citation import CitationService
from app.services.rag.contradiction import detect_contradiction
from app.services.rag.followup import FollowUpService
from app.services.rag.grounding import (
    evaluate_grounding,
    passes_numeric_guard,
    requires_strict_numeric_grounding,
)
from app.services.rag.generator import GeneratorService
from app.services.rag.query_intent import classify_intent, extract_entities, query_hint
from app.services.rag.query_rewrite import rewrite_query
from app.services.rag.retriever import RetrieverService
from app.services.rag.self_check import assess_retrieval
from app.services.governance_state import is_authority_verified
from app.utils.metrics import (
    QA_AUTHORITY_UNVERIFIED_TOTAL,
    QA_COMPLETED_TOTAL,
    QA_DEGRADED_TOTAL,
    QA_FIRST_TOKEN_LATENCY_SECONDS,
    QA_GENERATION_LATENCY_SECONDS,
    QA_GROUNDING_FAILED_TOTAL,
    QA_NEED_HUMAN_TOTAL,
    QA_REQUESTS_TOTAL,
    QA_RETRIEVAL_LATENCY_SECONDS,
    QA_TOTAL_LATENCY_SECONDS,
)

_SETTINGS = get_settings()


def _merge_retrieval_query(question: str, rewritten: str) -> str:
    """Keep exact codes/names from the user even when an LLM rewrite expands them."""
    original = (question or "").strip()
    expanded = (rewritten or "").strip()
    if not expanded or expanded == original:
        return original
    return f"{original} {expanded}"


class QAService:
    def __init__(self) -> None:
        self.retriever = RetrieverService()
        self.generator = GeneratorService()
        self.citation = CitationService()
        self.followup = FollowUpService()

    # ---- helpers ----
    @staticmethod
    def _citation_dict(c) -> dict:
        return {
            "clause_id": c.clause_id,
            "file_title": c.file_title,
            "regulation_code": c.regulation_code,
            "clause_no": c.clause_no,
            "excerpt": c.excerpt,
            "consistent": c.consistent,
            "source_page": c.source_page,
            "content_hash": c.content_hash,
        }

    @staticmethod
    async def _safe_commit(session: AsyncSession) -> None:
        try:
            await session.commit()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _degradation_reason(exc: Exception) -> str:
        """Expose a stable reason code without leaking provider error details."""
        if isinstance(exc, EmbeddingError):
            return "embedding_unavailable"
        if isinstance(exc, LLMTimeoutError):
            return "model_unavailable"
        return "retrieval_unavailable"

    @staticmethod
    def _honest_insufficient_text(question: str) -> str:
        """确定性「诚实不足」文本：不硬编结论，明确说明未覆盖并引导转人工。"""
        return (
            "根据现有制度库，暂未检索到足以确定回答您问题的条款，为避免给出错误结论，本次不生成制度解读。\n"
            "您可在下方「制度依据」中查看最接近的相关条款原文，或：\n"
            "1) 补充业务场景关键信息（金额及币种、境内外属性、审批层级、涉及部门）后重新提问；\n"
            "2) 转交对应职能审核骨干人工确认。"
        )

    @staticmethod
    def _numeric_guard_text() -> str:
        return (
            "本次自动解读未通过数值一致性校验，系统已阻止输出金额、比例或年限结论。\n\n"
            "下方制度依据已保留供核对；请补充计算起点、目标档级等口径后重试，"
            "或转制度责任部门人工确认。"
        )

    async def _controlled_degradation(
        self,
        session: AsyncSession,
        *,
        user,
        question: str,
        session_id: str | None,
        client_ip: str | None,
        reason: str,
        exc: Exception,
        is_evaluation: bool = False,
    ) -> dict:
        """Persist and return a truthful no-conclusion state for retrieval failures."""
        requested_id = session_id
        sid = requested_id or f"qa_{uuid.uuid4().hex[:12]}"
        # Do not overwrite a completed prior answer if a client retries with its ID.
        if await session.get(QASession, sid) is not None:
            sid = f"qa_{uuid.uuid4().hex[:12]}"

        answer = "制度检索服务暂不可用，本次未生成制度结论。请稍后重试或联系系统管理员确认模型连接。"
        session.add(
            QASession(
                session_id=sid,
                user_id=user.user_id,
                question=question,
                answer_interpret=answer,
                confidence=0.0,
                degraded=True,
                is_evaluation=is_evaluation,
                need_human=True,
            )
        )
        await session.flush()
        await record_audit(
            session,
            actor_id=user.user_id,
            action="qa.ask.degraded",
            target_type="qa",
            target_id=sid,
            detail=f"reason={reason};stage=retrieval;error_type={type(exc).__name__}",
            ip=client_ip,
        )
        QA_DEGRADED_TOTAL.labels(reason=reason).inc()
        return {
            "session_id": sid,
            "answer": answer,
            "need_human": True,
            "degraded": True,
            "degraded_reason": reason,
            "confidence": 0.0,
        }

    async def _selfcheck_refine(
        self,
        session: AsyncSession,
        user,
        permissions,
        query: str,
        candidates: list,
    ) -> list:
        """Agentic 自省闭环：评估检索充分性，不充分则改写重检索补召回。

        最多迭代 ``QA_SELFCHECK_MAX_ROUNDS`` 轮。每轮若 LLM 判定不充分，
        用其给出的 refined_query 二次检索，将新条款按 clause_id 去重合并，
        重排后进入下一轮。全部失败时优雅退回原候选集，绝不阻塞链路。
        """
        if not _SETTINGS.QA_SELFCHECK_ENABLED or not candidates:
            return candidates
        merged: list = list(candidates)
        seen = {c.clause.clause_id for c in merged}
        current_query = query

        for _ in range(_SETTINGS.QA_SELFCHECK_MAX_ROUNDS):
            top = max((c.score for c in merged), default=0.0)
            if top >= _SETTINGS.QA_SELFCHECK_TRIGGER_SCORE:
                break
            assess = await assess_retrieval(current_query, merged)
            if assess is None:
                break
            if assess["sufficient"] or assess["score"] >= 7:
                break
            refined = (assess.get("refined_query") or "").strip()
            if not refined or refined == current_query:
                break
            current_query = refined
            try:
                extra = await self.retriever.retrieve(
                    session, user, permissions, refined, top_k=_SETTINGS.RETRIEVE_TOP_K
                )
            except Exception:  # noqa: BLE001
                break
            added = 0
            for c in extra:
                if c.clause.clause_id not in seen:
                    seen.add(c.clause.clause_id)
                    merged.append(c)
                    added += 1
            if not added:
                break
            if _SETTINGS.QA_RERANK_ENABLED:
                merged = await self.retriever.rerank(current_query, merged)

        merged.sort(key=lambda c: c.score, reverse=True)
        return merged[: _SETTINGS.RETRIEVE_TOP_K + 3]

    # ---- streaming core ----
    async def ask_stream(
        self,
        session: AsyncSession,
        *,
        user,
        permissions,
        question: str,
        slots: dict | None = None,
        session_id: str | None = None,
        round_no: int = 1,
        client_ip: str | None = None,
        is_evaluation: bool = False,
    ):
        """Yield progress events for the full QA pipeline.

        Event types: phase | retrieve | followup | delta | citations | confidence | done
        """
        request_started = time.perf_counter()
        QA_REQUESTS_TOTAL.inc()
        # 1. query rewrite (graceful on timeout / disabled)
        rewritten = _merge_retrieval_query(question, await rewrite_query(question))
        # 追问收敛：员工按提示补充的槽位必须参与检索，否则同一问题分数不变、追问永不收敛
        if round_no > 1 and slots:
            supplement = " ".join(str(v) for v in slots.values() if str(v).strip())
            if supplement:
                rewritten = f"{rewritten} {supplement}".strip()

        # 2. retrieve
        yield {"type": "phase", "phase": "retrieving"}
        retrieval_started = time.perf_counter()
        try:
            initial_top_k = (
                max(_SETTINGS.RETRIEVE_TOP_K, _SETTINGS.QA_RERANK_CANDIDATES)
                if _SETTINGS.QA_RERANK_ENABLED
                else _SETTINGS.RETRIEVE_TOP_K
            )
            candidates = await self.retriever.retrieve(
                session, user, permissions, rewritten, top_k=initial_top_k,
            )
        except Exception as exc:  # external model/vector failures must not become HTTP 500
            QA_RETRIEVAL_LATENCY_SECONDS.observe(time.perf_counter() - retrieval_started)
            reason = self._degradation_reason(exc)
            degraded = await self._controlled_degradation(
                session,
                user=user,
                question=question,
                session_id=session_id,
                client_ip=client_ip,
                reason=reason,
                exc=exc,
                is_evaluation=is_evaluation,
            )
            yield {"type": "degraded", "reason": reason}
            yield {"type": "done", **degraded}
            QA_COMPLETED_TOTAL.inc()
            QA_NEED_HUMAN_TOTAL.inc()
            QA_TOTAL_LATENCY_SECONDS.observe(time.perf_counter() - request_started)
            await self._safe_commit(session)
            return
        QA_RETRIEVAL_LATENCY_SECONDS.observe(time.perf_counter() - retrieval_started)

        if not candidates:
            await record_audit(
                session, actor_id=user.user_id, action="qa.ask.empty",
                target_type="qa", detail=question, ip=client_ip,
            )
            yield {
                "type": "done",
                "session_id": session_id or f"qa_{uuid.uuid4().hex[:12]}",
                "answer": "未检索到与您问题相关的制度条款。建议补充业务场景关键信息（金额、境内外、审批层级等）后重新提问，或联系职能审核骨干确认。",
                "need_human": True,
                "degraded": True,
                "degraded_reason": "no_retrieval_result",
                "confidence": 0.0,
            }
            QA_COMPLETED_TOTAL.inc()
            QA_NEED_HUMAN_TOTAL.inc()
            QA_TOTAL_LATENCY_SECONDS.observe(time.perf_counter() - request_started)
            await self._safe_commit(session)
            return

        yield {"type": "retrieve", "count": len(candidates)}

        # 3. rerank (graceful)
        if _SETTINGS.QA_RERANK_ENABLED:
            candidates = await self.retriever.rerank(rewritten, candidates)

        # 3.5 agentic self-check refine（不充分则改写重检索补召回）
        candidates = await self._selfcheck_refine(session, user, permissions, rewritten, candidates)

        # 4. dynamic follow-up decision
        filled = self.followup.detect_slots(question, slots)
        missing_rule = self.followup.missing_slots(question, filled, round_no)
        top_score = max((c.score for c in candidates), default=0.0)
        # 只在第一轮追问；round>=2 员工已补充过信息，仍低分说明库里确实没有，
        # 继续追问只会无限循环——直接生成并明确提示转人工。
        if (missing_rule or top_score < _SETTINGS.QA_DYNAMIC_FOLLOWUP_SCORE) and round_no == 1:
            # Deterministic business slots always win. Asking an LLM after the
            # system already knows the missing fields can overwrite them with
            # nonsense such as asking the employee to supply the rule's own
            # M2→M3 duration. Dynamic follow-up is only a last resort for weak
            # retrieval when no governed slot definition exists.
            if missing_rule:
                fu = self.followup.build_followup(missing_rule, round_no)
            else:
                dyn = await self.followup.dynamic_followup(question, candidates, round_no)
                fu = dyn or self.followup.build_followup(["补充信息"], round_no)
            yield {"type": "followup", "data": fu}
            yield {
                "type": "done",
                "session_id": session_id or f"qa_{uuid.uuid4().hex[:12]}",
                "followup": True,
                "need_human": False,
                "degraded": False,
                "confidence": 0.0,
            }
            QA_TOTAL_LATENCY_SECONDS.observe(time.perf_counter() - request_started)
            await self._safe_commit(session)
            return

        # 4.5 诚实降级：自省+追问均用尽仍低分 → 明确「制度库未覆盖」，不硬编结论
        honest_insufficient = top_score < _SETTINGS.QA_DYNAMIC_FOLLOWUP_SCORE and round_no > 1

        # 5. contradiction check 与 6. 生成并发：矛盾检测后台执行，不与生成抢串行时间。
        #    detect_contradiction 内部已 try/except，绝不会抛出、不会阻塞。
        contra_task = asyncio.create_task(detect_contradiction(question, candidates))

        # 5.5 意图分类 + 实体抽取（规则驱动，零额外调用），驱动生成层差异化排版
        intent = classify_intent(question)
        entities = extract_entities(question)
        intent_hint = query_hint(intent, entities)
        strict_numeric = requires_strict_numeric_grounding(question)

        # 6. streaming generation（诚实降级时跳过 LLM，用确定性诚实文本）
        yield {"type": "phase", "phase": "generating"}
        state: dict = {"degraded": False}
        generation_started = time.perf_counter()
        first_token_observed = False
        if honest_insufficient:
            answer = self._honest_insufficient_text(question)
            QA_FIRST_TOKEN_LATENCY_SECONDS.observe(time.perf_counter() - request_started)
            first_token_observed = True
            yield {"type": "delta", "text": answer}
            degraded = False
        else:
            answer_parts: list[str] = []
            async for tok in self.generator.generate_stream(question, candidates, filled, state, intent_hint):
                if not first_token_observed:
                    QA_FIRST_TOKEN_LATENCY_SECONDS.observe(time.perf_counter() - request_started)
                    first_token_observed = True
                answer_parts.append(tok)
                # High-risk numeric answers are buffered until deterministic
                # grounding/arithmetic validation passes.
                if not strict_numeric:
                    yield {"type": "delta", "text": tok}
            answer = "".join(answer_parts)
            degraded = bool(state.get("degraded"))
        QA_GENERATION_LATENCY_SECONDS.observe(time.perf_counter() - generation_started)

        # 生成完成后回收矛盾检测结果（此时通常已完成，几乎不额外耗时）
        contra, contra_detail = await contra_task

        # 7. citations
        citations = self.citation.build_citations(candidates)
        clause_map = {c.clause.clause_id: c.clause.content for c in candidates}
        _ok, citations = self.citation.verify(citations, clause_map)
        yield {"type": "citations", "data": [self._citation_dict(c) for c in citations]}

        # 7.5 claim-level grounding and authority gate. Source-card integrity is
        # not enough: every substantive answer claim must carry a valid [n], and
        # unverified legacy material must never become an authoritative answer.
        grounding = evaluate_grounding(answer, candidates)
        numeric_blocked = False
        if strict_numeric and not degraded and not grounding.passed:
            revised = await self.generator.revise_for_grounding(
                question, candidates, answer, grounding.to_dict(), intent_hint,
            )
            if revised:
                revised_grounding = evaluate_grounding(revised, candidates)
                if passes_numeric_guard(revised_grounding):
                    answer = revised
                    grounding = revised_grounding
            if not passes_numeric_guard(grounding):
                numeric_blocked = True
                answer = self._numeric_guard_text()
        if strict_numeric:
            # Nothing from a high-risk draft has reached the client yet.
            yield {"type": "delta", "text": answer}
        # Only cited sources participate in the authority gate. An unverified
        # low-ranked retrieval candidate must not invalidate an otherwise fully
        # authoritative answer, while an uncited answer can never pass.
        authority_verified = bool(grounding.referenced_indices) and all(
            is_authority_verified(candidates[idx - 1].file)
            for idx in grounding.referenced_indices
        )
        quality_warnings: list[str] = []
        if not grounding.passed:
            quality_warnings.append("回答未通过逐结论引用校验，必须人工复核")
        if not authority_verified:
            quality_warnings.append("引用资料来源尚未确认，可由维护者本人确认后继续使用")
        if numeric_blocked:
            quality_warnings.append("数值结论未通过确定性一致性校验，已阻止自动输出")

        # 8. confidence (with contradiction penalty)
        base_conf = min(1.0, sum(c.score for c in candidates) / len(candidates)) if candidates else 0.0
        confidence = round(base_conf * (0.7 if contra else 1.0), 3)
        # LLM 诚实判定「信息不足」时，置信度与转人工联动降级，避免虚高置信误导
        _insufficient_markers = ("信息不足", "无法确定", "未涉及", "未覆盖", "无法判断", "无直接适用", "未检索到")
        llm_says_insufficient = any(m in answer for m in _insufficient_markers)
        if llm_says_insufficient:
            confidence = min(confidence, 0.35)
        if not grounding.passed or not authority_verified:
            confidence = min(confidence, 0.35)
        if numeric_blocked:
            confidence = 0.0
        need_human = (
            confidence < 0.4 or contra or honest_insufficient or numeric_blocked or llm_says_insufficient
            or not grounding.passed or not authority_verified
        )
        QA_COMPLETED_TOTAL.inc()
        QA_TOTAL_LATENCY_SECONDS.observe(time.perf_counter() - request_started)
        if need_human:
            QA_NEED_HUMAN_TOTAL.inc()
        if not grounding.passed:
            QA_GROUNDING_FAILED_TOTAL.inc()
        if not authority_verified:
            QA_AUTHORITY_UNVERIFIED_TOTAL.inc()

        # 9. persist
        new_session_id = session_id or f"qa_{uuid.uuid4().hex[:12]}"
        qa_session = QASession(
            session_id=new_session_id,
            user_id=user.user_id,
            question=question,
            answer_interpret=answer,
            confidence=confidence,
            degraded=degraded,
            is_evaluation=is_evaluation,
            need_human=need_human,
            grounding_passed=grounding.passed,
            grounding_coverage=grounding.coverage_rate,
            authority_verified=authority_verified,
        )
        session.add(qa_session)
        for cit in citations:
            session.add(
                QACitation(
                    session_id=new_session_id,
                    clause_id=cit.clause_id,
                    file_title=cit.file_title,
                    clause_no=cit.clause_no,
                    excerpt=cit.excerpt,
                    consistent=cit.consistent,
                    source_page=cit.source_page,
                    content_hash=cit.content_hash,
                )
            )
        await session.flush()
        await record_audit(
            session, actor_id=user.user_id, action="qa.ask",
            target_type="qa", target_id=new_session_id,
            detail=(
                f"clauses={len(citations)};conf={confidence};degraded={degraded};contra={contra};"
                f"grounded={grounding.passed};coverage={grounding.coverage_rate};"
                f"authority_verified={authority_verified}"
            ),
            ip=client_ip,
        )
        yield {
            "type": "confidence",
            "value": confidence,
            "contradiction": contra,
            "detail": contra_detail,
        }
        yield {
            "type": "done",
            "session_id": new_session_id,
            "answer": answer,
            "need_human": need_human,
            "degraded": degraded,
            "confidence": confidence,
            "insufficient": honest_insufficient or numeric_blocked,
            "grounding_passed": grounding.passed,
            "grounding_coverage": grounding.coverage_rate,
            "grounding_report": grounding.to_dict(),
            "authority_verified": authority_verified,
            "quality_warnings": quality_warnings,
        }
        await self._safe_commit(session)

    # ---- legacy synchronous wrapper (backward compatible, /qa/ask) ----
    async def ask(
        self,
        session: AsyncSession,
        *,
        user,
        permissions,
        question: str,
        slots: dict | None = None,
        session_id: str | None = None,
        round_no: int = 1,
        client_ip: str | None = None,
        is_evaluation: bool = False,
    ) -> dict:
        events = [
            ev
            async for ev in self.ask_stream(
                session, user=user, permissions=permissions, question=question,
                slots=slots, session_id=session_id, round_no=round_no, client_ip=client_ip,
                is_evaluation=is_evaluation,
            )
        ]
        answer = ""
        citations: list = []
        confidence = 0.0
        degraded = False
        degraded_reason = None
        need_human = False
        follow_up = None
        grounding_passed = False
        grounding_coverage = 0.0
        authority_verified = False
        quality_warnings: list[str] = []
        sid = session_id or f"qa_{uuid.uuid4().hex[:12]}"
        for ev in events:
            if ev["type"] == "delta":
                answer += ev["text"]
            elif ev["type"] == "citations":
                citations = ev["data"]
            elif ev["type"] == "confidence":
                confidence = ev["value"]
            elif ev["type"] == "followup":
                follow_up = ev["data"]
            elif ev["type"] == "done":
                sid = ev.get("session_id", sid)
                need_human = ev.get("need_human", need_human)
                degraded = ev.get("degraded", degraded)
                degraded_reason = ev.get("degraded_reason", degraded_reason)
                confidence = ev.get("confidence", confidence)
                if ev.get("answer"):
                    answer = ev["answer"]
                grounding_passed = ev.get("grounding_passed", grounding_passed)
                grounding_coverage = ev.get("grounding_coverage", grounding_coverage)
                authority_verified = ev.get("authority_verified", authority_verified)
                quality_warnings = ev.get("quality_warnings", quality_warnings)
        return {
            "session_id": sid,
            "answer_interpret": answer,
            "citations": citations,
            "confidence": confidence,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "follow_up": follow_up,
            "need_human": need_human,
            "grounding_passed": grounding_passed,
            "grounding_coverage": grounding_coverage,
            "authority_verified": authority_verified,
            "quality_warnings": quality_warnings,
        }
