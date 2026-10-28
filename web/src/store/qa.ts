import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as qaApi from '@/api/qa'
import type { Citation, FollowUp, QAAskResponse } from '@/api/qa'
import * as trialApi from '@/api/trial'

export type QAPhase = '' | 'retrieving' | 'generating' | 'done'

/** Pinia store driving the QA view with streaming-first consumption. */
export const useQaStore = defineStore('qa', () => {
  const question = ref('')
  const submittedQuestion = ref('')
  const loading = ref(false)
  const phase = ref<QAPhase>('')
  const streamingText = ref('')
  const citations = ref<Citation[]>([])
  const confidence = ref(0)
  const degraded = ref(false)
  const degradedReason = ref<string | null>(null)
  const needHuman = ref(false)
  const groundingPassed = ref(false)
  const groundingCoverage = ref(0)
  const authorityVerified = ref(false)
  const qualityWarnings = ref<string[]>([])
  const insufficient = ref(false)
  const contradiction = ref(false)
  const contraDetail = ref('')
  const followUp = ref<FollowUp | null>(null)
  const answer = ref<QAAskResponse | null>(null)
  const error = ref('')
  const sessionId = ref<string | null>(null)
  const historical = ref(false)
  const restoredAt = ref<string | null>(null)
  const relatedCases = ref<qaApi.RelatedCase[]>([])
  const relatedError = ref('')
  const recordedFeedback = ref<string[]>([])
  const round = ref(1)
  const trialMode = ref(localStorage.getItem('zg_trial_mode') === 'true')
  let requestStartedAt = 0
  let firstTokenAt = 0
  let requestVersion = 0
  let controller: AbortController | null = null
  let confirmedSlots: Record<string, string> = {}
  const quick = [
    '境外项目变更款50万美元由谁审批？',
    '差旅费报销需要提交哪些材料？',
    '驻外人员住宿标准是多少？',
  ]

  /** Clear all per-turn transient state before firing a new request. */
  function resetStreamState() {
    error.value = ''
    phase.value = ''
    streamingText.value = ''
    citations.value = []
    confidence.value = 0
    degraded.value = false
    degradedReason.value = null
    needHuman.value = false
    groundingPassed.value = false
    groundingCoverage.value = 0
    authorityVerified.value = false
    qualityWarnings.value = []
    insufficient.value = false
    contradiction.value = false
    contraDetail.value = ''
    followUp.value = null
    answer.value = null
  }

  /** Single event sink for the NDJSON stream. Mutates the refs the view reads. */
  function onEvent(ev: any) {
    switch (ev.type) {
      case 'phase':
        phase.value = ev.phase
        break
      case 'retrieve':
        phase.value = 'retrieving'
        break
      case 'followup':
        followUp.value = ev.data
        break
      case 'delta':
        if (!firstTokenAt) firstTokenAt = performance.now()
        streamingText.value += ev.text
        phase.value = 'generating'
        break
      case 'citations':
        citations.value = ev.data
        break
      case 'confidence':
        confidence.value = ev.value
        contradiction.value = !!ev.contradiction
        contraDetail.value = ev.detail || ''
        break
      case 'done':
        phase.value = 'done'
        sessionId.value = ev.session_id
        if (ev.followup) break // 追问分支：由 followUp ref 接管，不渲染答案块
        // The backend may replace a buffered high-risk numeric draft after its
        // deterministic guard runs. The final audited answer always wins.
        if (typeof ev.answer === 'string') streamingText.value = ev.answer
        needHuman.value = !!ev.need_human
        insufficient.value = !!ev.insufficient
        degraded.value = !!ev.degraded
        degradedReason.value = ev.degraded_reason || null
        confidence.value = ev.confidence ?? confidence.value
        groundingPassed.value = !!ev.grounding_passed
        groundingCoverage.value = ev.grounding_coverage ?? 0
        authorityVerified.value = !!ev.authority_verified
        qualityWarnings.value = ev.quality_warnings || []
        answer.value = {
          session_id: ev.session_id,
          answer_interpret: ev.answer ?? streamingText.value,
          citations: citations.value,
          confidence: confidence.value,
          degraded: degraded.value,
          degraded_reason: degradedReason.value,
          follow_up: null,
          need_human: needHuman.value,
          grounding_passed: groundingPassed.value,
          grounding_coverage: groundingCoverage.value,
          authority_verified: authorityVerified.value,
          quality_warnings: qualityWarnings.value,
        }
        break
      case 'error':
        phase.value = 'done'
        error.value = ev.message || '制度咨询服务暂不可用，请稍后重试。'
        streamingText.value = ''
        break
    }
  }

  async function ask() {
    if (!question.value.trim() || loading.value) return
    sessionId.value = null
    round.value = 1
    confirmedSlots = {}
    historical.value = false
    restoredAt.value = null
    relatedCases.value = []
    recordedFeedback.value = []
    await runRequest({})
  }

  async function answerFollowUp(slots: Record<string, string>) {
    if (!question.value.trim() || loading.value) return
    confirmedSlots = { ...confirmedSlots, ...slots }
    await runRequest(confirmedSlots)
  }

  async function runRequest(slots: Record<string, string>) {
    const version = ++requestVersion
    const requestQuestion = question.value.trim()
    submittedQuestion.value = requestQuestion
    controller?.abort()
    controller = new AbortController()
    loading.value = true
    resetStreamState()
    requestStartedAt = performance.now()
    firstTokenAt = 0
    if (trialMode.value) void trialApi.recordEvent({ event_type: 'qa_started', session_id: sessionId.value, is_trial: true }).catch(() => undefined)
    try {
      await qaApi.askStream(
        { question: requestQuestion, session_id: sessionId.value || undefined, round: round.value, slots },
        (event) => { if (version === requestVersion) onEvent(event) },
        controller.signal,
      )
      if (version !== requestVersion) return
      round.value += 1
      if (!error.value && (answer.value || followUp.value)) await recordTrialCompletion().catch(() => undefined)
      if (!error.value && !answer.value && !followUp.value) error.value = '咨询连接已结束，但未返回完整结果。请重试。'
      if (!error.value && answer.value) void refreshRelatedCases()
    } catch (e: any) {
      if (version !== requestVersion || e?.name === 'AbortError') return
      phase.value = 'done'
      streamingText.value = ''
      error.value = e?.message || '网络连接失败，请检查连接后重试。'
    } finally {
      if (version === requestVersion) { loading.value = false; controller = null }
    }
  }

  function clear() {
    ++requestVersion
    controller?.abort()
    controller = null
    loading.value = false
    question.value = ''
    submittedQuestion.value = ''
    resetStreamState()
    sessionId.value = null
    round.value = 1
    confirmedSlots = {}
    historical.value = false
    restoredAt.value = null
    relatedCases.value = []
    relatedError.value = ''
    recordedFeedback.value = []
  }

  async function restoreSession(id: string) {
    clear()
    const version = requestVersion
    loading.value = true
    try {
      const record = await qaApi.sessionDetail(id)
      if (version !== requestVersion) return
      question.value = record.question
      submittedQuestion.value = record.question
      sessionId.value = record.session_id
      historical.value = true
      restoredAt.value = record.created_at
      relatedCases.value = record.related_cases || []
      recordedFeedback.value = record.feedback_types || []
      phase.value = 'done'
      confidence.value = record.confidence
      degraded.value = record.degraded
      needHuman.value = record.need_human
      groundingPassed.value = record.grounding_passed
      groundingCoverage.value = record.grounding_coverage
      authorityVerified.value = record.authority_verified
      citations.value = record.citations || []
      streamingText.value = record.completed ? record.answer_interpret || '' : ''
      if (record.completed) answer.value = {
        session_id: record.session_id, answer_interpret: record.answer_interpret, citations: record.citations,
        confidence: record.confidence, degraded: record.degraded, degraded_reason: null, follow_up: null,
        need_human: record.need_human, grounding_passed: record.grounding_passed,
        grounding_coverage: record.grounding_coverage, authority_verified: record.authority_verified, quality_warnings: [],
      }
    } catch (e: any) {
      if (version === requestVersion) error.value = e?.response?.status === 404 ? '咨询记录不存在或不属于当前账号。' : e?.response?.data?.message || '咨询记录读取失败，请检查连接后重试。'
    } finally { if (version === requestVersion) loading.value = false }
  }

  async function refreshRelatedCases() {
    const sid = sessionId.value
    if (!sid) return
    const version = requestVersion
    relatedError.value = ''
    try {
      const record = await qaApi.sessionDetail(sid)
      if (version === requestVersion && sessionId.value === sid) {
        relatedCases.value = record.related_cases || []
        recordedFeedback.value = record.feedback_types || []
      }
    } catch (e: any) { if (version === requestVersion) relatedError.value = e?.message || '关联事项读取失败，请重试。' }
  }

  function cancel() {
    ++requestVersion
    controller?.abort()
    controller = null
    loading.value = false
    resetStreamState()
    error.value = '查询已停止。可以修改问题后重新提交。'
  }

  async function retry() {
    if (!question.value.trim() || loading.value) return
    if (historical.value) { await ask(); return }
    if (question.value.trim() !== submittedQuestion.value) { await ask(); return }
    await runRequest({ ...confirmedSlots })
  }

  async function feedback(type: string, content?: string) {
    const sid = sessionId.value || answer.value?.session_id
    if (!sid) return
    const version = requestVersion
    await qaApi.feedback({ session_id: sid, type, content })
    if (version !== requestVersion || sessionId.value !== sid) return
    if (!recordedFeedback.value.includes(type)) recordedFeedback.value.push(type)
    if (trialMode.value && ['like', 'correct'].includes(type)) {
      void trialApi.recordEvent({
        event_type: type === 'like' ? 'feedback_like' : 'feedback_correct',
        session_id: sid, is_trial: true,
      }).catch(() => undefined)
    }
  }

  async function recordTrialCompletion() {
    if (!trialMode.value) return
    const now = performance.now()
    await trialApi.recordEvent({
      event_type: 'qa_completed',
      session_id: sessionId.value,
      result_state: followUp.value ? 'followup' : degraded.value ? 'degraded' : 'completed',
      need_human: needHuman.value,
      authority_verified: authorityVerified.value,
      grounding_passed: groundingPassed.value,
      latency_first_token_ms: firstTokenAt ? Math.round(firstTokenAt - requestStartedAt) : null,
      latency_total_ms: Math.round(now - requestStartedAt),
      is_trial: true,
    })
    if (needHuman.value) {
      await trialApi.recordEvent({
        event_type: 'manual_review_requested', session_id: sessionId.value,
        result_state: 'requested', need_human: true, is_trial: true,
      })
    }
  }

  function setTrialMode(enabled: boolean) {
    trialMode.value = enabled
    localStorage.setItem('zg_trial_mode', String(enabled))
  }

  function recordCitationOpen(clauseId: string) {
    if (!trialMode.value) return
    void trialApi.recordEvent({ event_type: 'citation_opened', session_id: sessionId.value, result_state: clauseId, is_trial: true }).catch(() => undefined)
  }

  return {
    question,
    submittedQuestion,
    answer,
    error,
    followUp,
    loading,
    quick,
    sessionId,
    historical,
    restoredAt,
    relatedCases,
    relatedError,
    recordedFeedback,
    round,
    phase,
    streamingText,
    citations,
    confidence,
    degraded,
    degradedReason,
    needHuman,
    groundingPassed,
    groundingCoverage,
    authorityVerified,
    qualityWarnings,
    insufficient,
    contradiction,
    contraDetail,
    trialMode,
    ask,
    answerFollowUp,
    clear,
    cancel,
    retry,
    restoreSession,
    refreshRelatedCases,
    feedback,
    setTrialMode,
    recordCitationOpen,
  }
})
