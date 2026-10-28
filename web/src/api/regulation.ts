import { post, get, del } from './request'

export interface RegulationRow {
  source_kind?: 'regulation' | 'asset'; asset_version_id?: string
  file_id: string; title: string; source: string; version: string; status: string
  regulation_code: string; secret_level: string; domain: string; org_path: string
  effective_date: string | null; expiry_date?: string | null; owner_org?: string | null
  authority_verified: boolean; authority_gaps: string[]; tags: string[]
  source_verification?: 'maintainer' | 'metadata' | 'unconfirmed'
  has_original: boolean; document_count: number; replaces_file_id?: string | null
  clause_count?: number
  reviewed_at?: string | null; review_note?: string | null
  documents?: Array<{ doc_id: string; doc_type: string; filename: string; title: string; mime: string }>
}

export interface ClauseRow {
  clause_id: string; file_id: string; chapter: string | null; clause_no: string; content: string
  source_page?: number | null; source_locator?: string | null; content_hash?: string | null
  heading_path?: string[]; block_type?: string; scenario_tags?: string[]
}

export function listRegulations() {
  return get<any[]>('/regulations')
}
export function confirmRegulationSources(file_ids: string[], note: string) {
  return post<{ count: number; file_ids: string[]; source_verification: string }>('/regulations/source-confirmations', { file_ids, note }, { timeout: 300_000 })
}
export function listCategories() {
  return get<{ name: string; count: number }[]>('/regulations/categories')
}
export interface GovernanceGap {
  file_id: string
  title: string
  status: string
  missing_fields: string[]
  regulation_code: string | null
  effective_date: string | null
  owner_org: string | null
  domain: string
}
export function governanceGaps() {
  return get<{ total: number; items: GovernanceGap[] }>('/regulations/governance/gaps')
}
export function updateMetadata(fileId: string, body: { regulation_code?: string; effective_date?: string; expiry_date?: string; owner_org?: string; domain?: string; evidence_note: string }) {
  return post<any>(`/regulations/${fileId}/metadata`, body)
}
export function regulationDetail(id: string) {
  return get<any>('/regulations/' + id)
}
export function listClauses(fileId: string) {
  return get<any[]>('/regulations/' + fileId + '/clauses')
}
export function uploadRegulation(form: FormData) {
  // 上传接口已异步化，会立即返回（仅存文件+建 processing 记录）；
  // 这里仍给较长超时以容纳大文件上传本身。
  return post<{ file_id: string; status: string; clause_count: number }>('/regulations/upload', form, { timeout: 60000 })
}
export interface IngestionJobOut {
  job_id: string
  file_id: string
  status: string
  attempt_count: number
  last_error: string | null
  started_at: string | null
  finished_at: string | null
}
export function ingestionStatus(fileId: string) {
  return get<IngestionJobOut>('/regulations/' + fileId + '/ingestion')
}
export function retryIngestion(fileId: string) {
  return post<{ file_id: string; status: string; job: IngestionJobOut }>('/regulations/' + fileId + '/ingestion/retry')
}
export function reparseRegulation(fileId: string) {
  return post<any>('/regulations/' + fileId + '/reparse', {}, { timeout: 300000 })
}
export function listPendingReviews() {
  return get<any[]>('/regulations/reviews/pending')
}
export function previewPendingReview(fileId: string) {
  return get<any>('/regulations/reviews/' + fileId + '/preview')
}
export function reviewRegulation(fileId: string, body: { approved: boolean; note: string }) {
  return post<any>('/regulations/' + fileId + '/review', body)
}
export function batchReviewRegulations(fileIds: string[], approved = true, note = '批量审核') {
  return post<{ approved: number; skipped: number }>('/regulations/reviews/batch', { file_ids: fileIds, approved, note })
}
export function listFeedbacks(resolved?: boolean) {
  return get<any[]>('/qa/feedbacks' + (resolved === undefined ? '' : `?resolved=${resolved}`))
}
export function resolveFeedback(fbId: string, note: string) {
  return post<any>(`/qa/feedbacks/${fbId}/resolve`, { note })
}
export function resubmitRegulationReview(fileId: string) {
  return post<any>('/regulations/' + fileId + '/review/resubmit')
}
export function annotateClause(clauseId: string, body: { scenario_tags?: string[]; secret_level?: string; permission_level?: string }) {
  return post('/regulations/clauses/' + clauseId + '/annotate', body)
}
export function deleteRegulation(id: string) {
  return del('/regulations/' + id)
}
export function previewRegulation(id: string) {
  return get<any>('/regulations/' + id + '/preview')
}
/** 取回原始文件字节（blob），用于浏览器下载/预览。绕过 JSON 拦截器，用原生 fetch。 */
export async function downloadRegulation(id: string): Promise<Blob> {
  return downloadFile('/regulations/' + encodeURIComponent(id) + '/download')
}

export async function downloadDocument(fileId: string, documentId: string): Promise<Blob> {
  return downloadFile('/regulations/' + encodeURIComponent(fileId) + '/documents/' + encodeURIComponent(documentId) + '/download')
}

export async function downloadAssetDocument(versionId: string, documentId: string): Promise<Blob> {
  return downloadFile('/assets/versions/' + encodeURIComponent(versionId) + '/documents/' + encodeURIComponent(documentId) + '/download')
}

export function assetReading(versionId: string, params?: { offset?: number; limit?: number; keyword?: string }) {
  return get<{clauses: ClauseRow[]; total: number}>('/assets/versions/' + encodeURIComponent(versionId) + '/reading', params)
}

async function downloadFile(path: string): Promise<Blob> {
  const token = localStorage.getItem('zg_token')
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 30000)
  try {
    const resp = await fetch('/api/v1' + path, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}, signal: controller.signal,
    })
    if (resp.status === 401) {
      localStorage.removeItem('zg_token'); localStorage.removeItem('zg_role')
      location.href = '/login?redirect=' + encodeURIComponent(location.pathname + location.search + location.hash)
    }
    if (!resp.ok) throw new Error('文件暂不可下载，请核对来源或联系资料管理员。')
    return await resp.blob()
  } catch (error) {
    if (controller.signal.aborted) throw new Error('下载超时，请稍后重试或联系资料管理员。')
    throw error
  } finally { clearTimeout(timeout) }
}
