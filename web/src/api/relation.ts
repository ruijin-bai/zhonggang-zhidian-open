import { post, get, del } from './request'

export interface GraphData {
  nodes: Array<{ id: string; title: string; version: string; status: string; org_path: string; secret_level: string; domain: string }>
  edges: Array<{ rel_id: string; from: string; to: string; type: string; type_label: string; note: string; confirmed_by: string | null }>
  conflicts: Array<{ from: string; to: string; note: string | null }>
}

export function createRelation(body: { from_id: string; to_id: string; rel_type: string; note?: string; confirmed_by?: string }) {
  return post('/relations', body)
}
export function listRelations() {
  return get('/relations')
}
export function graph() {
  return get<GraphData>('/relations/graph')
}
export function deleteRelation(id: string) {
  return del('/relations/' + id)
}
