import request, { get, post } from './request'

export interface AssetSummary {
  assets: number
  versions: number
  documents: number
  content_nodes: number
  parse_states: Record<string, number>
  version_ingestion_states: Record<string, number>
  benchmark_target: number
}

export interface AssetRow {
  asset_id: string
  asset_type: string
  title: string
  business_code: string
  issue_no: string
  secret_level: string
  version_id: string
  version_label: string
  release_state: string
  ingestion_state: string
  effective_date: string | null
  expiry_date: string | null
  document_count: number
  readable_unit_count: number
  legacy_file_id: string | null
  authority_gaps: string[]
  authority_verified: boolean
  source_verification: 'maintainer' | 'metadata' | 'unconfirmed'
}

export function summary() { return get<AssetSummary>('/assets/summary') }
export interface TaxonomyItem { value: string; label: string }
export interface AssetTaxonomy { asset_types: TaxonomyItem[]; document_roles: TaxonomyItem[]; node_types: TaxonomyItem[] }
export interface AssetDocument { document_id: string; filename: string; title: string; role: string; mandatory: boolean; normative: boolean; parse_disposition: string; size_bytes: number; parse_run_id: string | null; parse_status: string; quality_report: { node_count?: number; citable_count?: number; warnings?: string[]; [key: string]: unknown } }
export interface PublicationGate { publishable: boolean; errors: string[]; authority_gaps: string[]; citable_count: number; fingerprint: string }
export interface AssetVersion { version_id: string; version_label: string; release_state: string; ingestion_state: string; issue_no: string; issuer?: string; owner_org?: string | null; owner_org_name?: string | null; domain?: string; replacement_notice?: { previous_version_id: string; history_review_required: boolean; message: string; historical_case_count?: number } | null; effective_date?: string | null; expiry_date?: string | null; authority_gaps?: string[]; authority_verified: boolean; source_verification: 'maintainer' | 'metadata' | 'unconfirmed'; source_confirmation?: { kind: string; confirmed: boolean; actor_id: string; confirmed_at: string; note: string } | null; review_note?: string | null; reviewed_at?: string | null; publication_gate?: PublicationGate | null; activation_gate?: PublicationGate | null; documents: AssetDocument[] }
export interface AssetDetail { asset_id: string; title: string; asset_type: string; business_code: string; domain: string; secret_level: string; owner_org: string | null; versions: AssetVersion[] }
export interface ContentNode { node_id: string; parent_id: string | null; node_type: string; order_path: string; label: string; title: string; text: string; source_page: number | null; source_locator: string | null; sheet_name: string | null; cell_range: string | null; structure: { values?: string[]; [key: string]: unknown }; is_citable: boolean }
export interface DocumentTree { document_id: string; filename: string; parse_run_id?: string; total: number; offset: number; limit: number; nodes: ContentNode[] }
export interface ParseResult { document_id: string; status: string; error?: string }
export interface BenchmarkResult { found: number; requested: number; missing: string[]; version_ids?: string[] }
export interface PendingAssetReview { asset_id: string; title: string; version_id: string; version_label: string; issue_no: string; effective_date: string | null; ingestion_state: string }
export function pendingReviews() { return get<PendingAssetReview[]>('/assets/reviews/pending') }
export function submitVersion(versionId: string) { return post<{ release_state: string }>(`/assets/versions/${versionId}/submit`) }
export function activateVersion(versionId: string, note: string) { return post<{ release_state: string; source_verification: string }>(`/assets/versions/${versionId}/activate`, { note }) }
export function confirmSources(version_ids: string[], note: string) { return post<{ count: number; version_ids: string[] }>('/assets/source-confirmations', { version_ids, note }, { timeout: 300_000 }) }
export function reviewVersion(versionId: string, body: { decision: 'approve' | 'reject'; note: string }) { return post<{ release_state: string }>(`/assets/versions/${versionId}/review`, body) }
export function createRevision(versionId: string, version_label: string) { return post<{ asset_id: string; version_id: string }>(`/assets/versions/${versionId}/revision`, { version_label }) }
export function updateMetadata(versionId: string, body: { issue_no: string; issuer: string; effective_date: string | null; expiry_date: string | null; owner_org: string | null; domain: string; evidence_note: string }) { return request.patch(`/assets/versions/${versionId}/metadata`, body) }
export function updateRole(versionId: string, documentId: string, body: { role: string; mandatory: boolean; normative: boolean; evidence_note: string }) { return request.patch(`/assets/versions/${versionId}/documents/${documentId}/role`, body) }
export function taxonomy() { return get<AssetTaxonomy>('/assets/taxonomy') }
export function list(params?: Record<string, unknown>) { return get<AssetRow[]>('/assets', params) }
export function detail(assetId: string) { return get<AssetDetail>(`/assets/${assetId}`) }
export function tree(documentId: string, params?: { offset?: number; limit?: number }) {
  return get<DocumentTree>(`/assets/documents/${documentId}/tree`, params)
}
export function parseDocument(documentId: string) {
  return post<ParseResult>(`/assets/documents/${documentId}/parse`, undefined, { timeout: 300_000 })
}
export function parseVersion(versionId: string) {
  return post<{ version_id: string; ingestion_state: string; documents: ParseResult[] }>(`/assets/versions/${versionId}/parse`, undefined, { timeout: 900_000 })
}
export function migrateBenchmarks(dryRun = true) {
  return post<BenchmarkResult>(`/assets/migration/benchmarks?dry_run=${dryRun}`, undefined, { timeout: 300_000 })
}
export function createPackage(form: FormData) {
  return post<{ asset_id: string; version_id: string; document_ids: string[]; ingestion_state: string }>('/assets', form, { timeout: 300_000 })
}
