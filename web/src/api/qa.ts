import { post, get } from './request'

export interface Citation {
  clause_id: string
  file_title: string
  regulation_code: string
  clause_no: string
  excerpt: string
  consistent: boolean
  source_page: number | null
  content_hash: string | null
}
export interface FollowUpPrompt {
  slot: string
  label: string
  options: string[]
}
export interface FollowUp {
  round: number
  missing: string[]
  prompts: FollowUpPrompt[]
}
export interface QAAskResponse {
  session_id: string
  answer_interpret: string
  citations: Citation[]
  confidence: number
  degraded: boolean
  degraded_reason: string | null
  follow_up: FollowUp | null
  need_human: boolean
  grounding_passed: boolean
  grounding_coverage: number
  authority_verified: boolean
  quality_warnings: string[]
}

export function ask(payload: {
  question: string
  session_id?: string
  slots?: Record<string, string>
  round?: number
}) {
  return post<QAAskResponse>('/qa/ask', payload)
}

export function feedback(payload: { session_id: string; type: string; content?: string }) {
  return post('/qa/feedback', payload)
}

export interface RelatedCase { case_id: string; case_no: string; title: string; status: string }
export interface QASessionSummary {
  session_id: string
  question: string
  answer_excerpt: string
  completed: boolean
  need_human: boolean
  degraded: boolean
  created_at: string | null
  linked_case_count: number
}
export interface QASessionDetail {
  session_id: string
  question: string
  answer_interpret: string
  citations: Citation[]
  confidence: number
  degraded: boolean
  need_human: boolean
  grounding_passed: boolean
  grounding_coverage: number
  authority_verified: boolean
  completed: boolean
  created_at: string | null
  related_cases: RelatedCase[]
  feedback_types: string[]
}
export function sessionDetail(id: string) {
  return get<QASessionDetail>('/qa/session/' + encodeURIComponent(id))
}
export function mySessions(params: { keyword?: string; offset?: number; limit?: number } = {}) {
  return get<{ items: QASessionSummary[]; total: number; offset: number; limit: number }>('/qa/sessions', params)
}

/**
 * Streaming QA: POST to /qa/ask/stream and parse the NDJSON event stream.
 * Unlike axios, fetch keeps the connection open until the server finishes, so a
 * slow LLM no longer triggers the 20s client timeout. `onEvent` is called per
 * server event: phase | retrieve | followup | delta | citations | confidence | done | error.
 */
export async function askStream(
  payload: { question: string; session_id?: string; slots?: Record<string, string>; round?: number },
  onEvent: (ev: any) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = (localStorage.getItem('zg_token') as string) || ''
  const resp = await fetch('/api/v1/qa/ask/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new Error(`流式问答请求失败（${resp.status}）`)
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, idx).trim()
      buf = buf.slice(idx + 1)
      if (!line) continue
      try {
        onEvent(JSON.parse(line))
      } catch {
        // 忽略单行解析错误
      }
    }
  }
  if (buf.trim()) {
    try {
      onEvent(JSON.parse(buf.trim()))
    } catch {
      if (typeof console !== 'undefined') console.warn('qa stream tail parse error')
    }
  }
}
