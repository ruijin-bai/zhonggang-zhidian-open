import { get } from './request'

export interface QualityDashboard {
  qa_total: number
  answered_total: number
  evaluation_run_total: number
  recall_rate: number | null
  citation_rate: number | null
  adopt_rate: number | null
  human_handoff_rate: number | null
  realtime_citation_rate: number | null
  realtime_avg_confidence: number | null
  degraded_rate: number | null
  grounding_rate: number | null
  authority_answer_rate: number | null
  source_anchor_rate: number | null
  evaluation_grounding_rate: number | null
  evaluation_answer_rate: number | null
  evaluation_authority_rate: number | null
  testset_total: number
  retrieval_smoke_total: number
  regulation_total: number
  regulation_current: number
  regulation_pending_review: number
  pending_asset_reviews: number
  regulation_authority_verified: number
  clause_total: number
  regulation_with_clauses: number
  pending_feedback_count: number
  case_total: number
  case_review_required: number
  case_confirmed: number
  active_rule_count: number
  open_impact_count: number
  open_high_impact_count: number
  correction_distribution: Array<{ type: string; count: number }>
  uncovered_scenarios: string[]
}

export function quality() {
  return get<QualityDashboard>('/dashboard/quality')
}

export interface WorkbenchSummary {
  role: string
  my_case_total: number
  my_case_open: number
  unread_pushes: number
  regulation_total: number
  relation_count: number
  impact_open: number
  active_rules: number
  pending_rule_reviews: number
  pending_regulation_reviews: number
  pending_asset_reviews: number
  pending_case_reviews: number
  pending_feedbacks: number
  ingestion_failures: number
  total_actions: number
}

export function workbench() {
  return get<WorkbenchSummary>('/dashboard/workbench')
}
