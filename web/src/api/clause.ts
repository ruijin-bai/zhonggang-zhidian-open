import { get } from './request'
import type { ClauseRow } from './regulation'

export interface ClauseDetail extends ClauseRow {
  file_title: string; file_version: string; file_status: string; secret_level: string; tags: string[]
  source_kind?: 'regulation' | 'asset'; document_title?: string | null
  historical?: boolean; snapshot_only?: boolean; asset_version_id?: string | null
}

export function clauseDetail(id: string, sessionId?: string) {
  return get<ClauseDetail>('/clauses/' + encodeURIComponent(id), sessionId ? {session_id: sessionId} : undefined)
}
