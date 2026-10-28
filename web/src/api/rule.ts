import { get, post } from './request'

export interface DecisionRuleOut {
  rule_id: string
  rule_key: string
  scenario: string
  rule_type: string
  priority: number
  status: string
  file_id: string
  clause_id: string
  file_title: string
  clause_no: string
  currency: string
  amount_min_minor: number | null
  amount_max_minor: number | null
  min_inclusive: boolean
  max_inclusive: boolean
  org_scope: string
  org_name?: string | null
  conditions: Record<string, unknown>
  approver_path: string[]
  required_materials: string[]
  risk_note: string | null
  review_note: string | null
  source_kind?: 'regulation' | 'asset'
  asset_version_id?: string | null
  retrieval_unit_id?: string | null
}
export interface RuleSource {
  source_kind: 'regulation' | 'asset'
  file_id: string
  title: string
  version: string
  asset_version_id?: string
}
export interface RuleSourceUnit {
  source_kind: 'regulation' | 'asset'
  file_id: string
  clause_id: string
  clause_no: string
  content: string
  asset_version_id?: string
  retrieval_unit_id?: string
  source_page?: number | null
  source_locator?: string | null
  content_hash?: string | null
}
export function sources(params?: { source_kind?: 'regulation' | 'asset'; file_id?: string; asset_version_id?: string; keyword?: string; offset?: number; limit?: number }) {
  return get<{ sources: RuleSource[]; units: RuleSourceUnit[]; total: number }>('/rules/sources', params)
}
export function listRules(params?: { status?: string }) { return get<DecisionRuleOut[]>('/rules', params) }
export function pendingRuleReviews() { return get<DecisionRuleOut[]>('/rules/reviews/pending') }
export function createRule(body: Record<string, unknown>) { return post<DecisionRuleOut>('/rules', body) }
export function reviewRule(ruleId: string, body: { approved: boolean; note: string }) { return post<DecisionRuleOut>(`/rules/${ruleId}/review`, body) }
export function activateRule(ruleId: string, body: { note: string }) { return post<DecisionRuleOut>(`/rules/${ruleId}/activate`, body) }
export interface RuleCoverageCandidate {
  scenario: string
  file_id: string
  file_title: string
  clause_id: string
  clause_no: string
  excerpt: string
  matched_keywords: string[]
  requires_business_review: boolean
  evidence_signals: { amount_mentions: string[]; currency_mentions: string[]; approval_mentions: string[]; material_mentions: string[] }
}
export function coverageCandidates() {
  return get<{ target_scenarios: number; candidate_count: number; active_rule_count: number; items: RuleCoverageCandidate[] }>('/rules/coverage')
}
