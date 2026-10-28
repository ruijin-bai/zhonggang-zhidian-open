import { post, get } from './request'

export interface PushRecordOut {
  push_id: string
  file_id: string | null
  target_role: string | null
  scenario_tag: string | null
  status: string
  digest: string
  created_by: string | null
  read_count: number
  unread_count: number
  push_time: string | null
}

export function notify(body: { file_id: string; require_review: boolean; target_role?: string; scenario_tag?: string; old_file_id?: string }) {
  return post('/push/notify', body)
}
export function center() {
  return get<{ pushes: PushRecordOut[]; total_unread: number }>('/push/center')
}
export function markRead(pushId: string, read = true) {
  return post('/push/receipt/' + pushId, { read })
}
export function markReadBatch(pushIds?: string[], read = true) {
  return post<{ updated: number }>('/push/receipts/batch', { push_ids: pushIds || null, read })
}
export function recall(pushId: string) {
  return post('/push/' + pushId + '/recall')
}
