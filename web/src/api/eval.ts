import { post, get, del } from './request'

export interface TestCase {
  case_id: string
  question: string
  expected_clause_ids: string[]
  standard_answer: string
  scenario_tag: string | null
  status: string
}

export function listCases(tag?: string) {
  return get<TestCase[]>('/eval/testset' + (tag ? '?scenario_tag=' + tag : ''))
}
export function createCase(body: { question: string; expected_clause_ids?: string[]; standard_answer?: string; scenario_tag?: string }) {
  return post('/eval/testset', body)
}
export function deleteCase(id: string) {
  return del('/eval/testset/' + id)
}
export function run(body: { case_ids?: string[]; reviewer?: string }) {
  return post<{
    total: number
    recall_pass: number
    citation_pass: number
    avg_score: number
    recall_rate: number
    runs: Array<{ run_id: string; case_id: string; recall_match: boolean; citation_match: boolean; score: number }>
  }>('/eval/run', body)
}
