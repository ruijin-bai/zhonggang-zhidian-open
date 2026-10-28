import { post } from './request'

export interface TrialEvent {
  event_type: 'qa_started' | 'qa_completed' | 'citation_opened' | 'feedback_like' | 'feedback_correct' | 'case_created' | 'case_evaluated' | 'manual_review_requested'
  session_id?: string | null
  scenario?: string | null
  result_state?: string | null
  need_human?: boolean | null
  authority_verified?: boolean | null
  grounding_passed?: boolean | null
  latency_first_token_ms?: number | null
  latency_total_ms?: number | null
  is_trial: boolean
}

export function recordEvent(data: TrialEvent) {
  return post<{ event_id: string }>('/trial/events', data)
}
