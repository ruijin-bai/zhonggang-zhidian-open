import { get, post } from './request'

export interface ImpactItem {
  item_id: string
  item_type: string
  object_type: string
  object_id: string | null
  severity: string
  status: string
  old_snapshot: Record<string, any>
  new_snapshot: Record<string, any>
  resolution: string | null
  resolved_by: string | null
  resolved_at: string | null
}
export interface ImpactRun {
  impact_id: string
  new_file_id: string
  old_file_id: string | null
  new_file_title: string
  new_file_version: string
  old_file_title: string | null
  old_file_version: string | null
  status: string
  summary: Record<string, number>
  confirmation_note: string | null
  items?: ImpactItem[]
}
export function listImpacts(status?: string) { return get<ImpactRun[]>('/impacts', status ? { status } : undefined) }
export function impactDetail(id: string) { return get<ImpactRun>('/impacts/' + id) }
export function resolveImpactItem(impactId: string, itemId: string, resolution: string) { return post<ImpactItem>(`/impacts/${impactId}/items/${itemId}/resolve`, { resolution }) }
export function confirmImpact(impactId: string, note: string) { return post<ImpactRun>(`/impacts/${impactId}/confirm`, { note }) }
