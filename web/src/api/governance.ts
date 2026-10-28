import { get, post } from './request'

export interface GovernanceTask {
  task_id: string
  task_key: string
  task_type: 'regulation_metadata' | 'rule_candidate'
  title: string
  file_id: string
  clause_id: string | null
  scenario: string | null
  status: 'open' | 'in_progress' | 'resolved' | 'dismissed'
  priority: 'normal' | 'high'
  missing_fields: string[]
  evidence: Record<string, any>
  assignee_id: string | null
  assignee_name: string | null
  due_date: string | null
  resolution_note: string | null
}

export function syncTasks() {
  return post<{ created: number; updated: number; resolved: number; metadata_files: number; rule_candidates: number }>('/governance/sync')
}
export function listTasks(params?: { task_type?: string; status?: string }) {
  return get<{ total: number; status_counts: Record<string, number>; items: GovernanceTask[] }>('/governance/tasks', params)
}
export function actOnTask(taskId: string, body: { action: string; note?: string; due_date?: string }) {
  return post<GovernanceTask>(`/governance/tasks/${taskId}/action`, body)
}
export function listOrgUnits() {
  return get<{ org_id: string; name: string; path: string }[]>('/governance/org-units')
}
