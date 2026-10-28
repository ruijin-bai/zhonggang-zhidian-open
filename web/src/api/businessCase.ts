import { get, post, put } from './request'

export interface BusinessCaseOut {
  case_id: string
  case_no: string
  requester_id: string
  scenario: string
  title: string
  org_path: string
  org_name?: string | null
  project_code: string | null
  amount_minor: number | null
  currency: string | null
  facts: Record<string, unknown>
  status: string
  risk_level: string
  need_human: boolean
  decision_summary: string | null
  decision_snapshot: Record<string, any>
  evaluated_at: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  review_note: string | null
}

export function createCase(body: Record<string, unknown>) {
  return post<BusinessCaseOut>('/cases', body)
}
export function evaluateCase(caseId: string) {
  return post<BusinessCaseOut>(`/cases/${caseId}/evaluate`)
}
export function updateCase(caseId: string, body: Record<string, unknown>) {
  return put<BusinessCaseOut>(`/cases/${caseId}`, body)
}
export function caseDetail(caseId: string) {
  return get<BusinessCaseOut>(`/cases/${caseId}`)
}
export function myCases() {
  return get<BusinessCaseOut[]>('/cases/mine')
}
export interface CaseFactField {
  key: string
  label: string
  kind: 'enum' | 'number' | 'boolean' | 'manual'
  options: { value: string | number | boolean; label: string }[]
}
export function caseContext() {
  return get<{ org_path: string; org_name: string; rule_counts: Record<string, number>; fact_fields: Record<string, CaseFactField[]> }>('/cases/context')
}
export function reviewQueue() {
  return get<BusinessCaseOut[]>('/cases/review-queue')
}
export function reviewCase(caseId: string, body: { confirmed: boolean; note: string; approver_path?: string[]; required_materials?: string[] }) {
  return post<BusinessCaseOut>(`/cases/${caseId}/review`, body)
}
