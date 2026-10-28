import { get, post } from './request'

export interface LibraryTarget { source_kind: 'regulation' | 'asset'; target_id: string; asset_version_id?: string | null }
export interface PersonalDocument extends LibraryTarget {
  title: string; version: string; status: string; regulation_code: string
  recorded_at: string; read_at: string | null; resume_clause_id: string | null; version_changed: boolean
}
export interface SavedAnswer { session_id: string; question: string; answer_excerpt: string; saved_at: string }
export interface PersonalPage<T> { items: T[]; total: number; offset: number; limit: number }
export function favorites(offset = 0, limit = 15, q = '') { return get<PersonalPage<PersonalDocument>>('/me/library/favorites', { offset, limit, q }) }
export function recent(offset = 0, limit = 15, q = '') { return get<PersonalPage<PersonalDocument>>('/me/library/recent', { offset, limit, q }) }
export function answerFavorites(offset = 0, limit = 15, q = '') { return get<PersonalPage<SavedAnswer>>('/me/library/answer-favorites', { offset, limit, q }) }
export function state(target: LibraryTarget) { return get<{ saved: boolean; reading: PersonalDocument | null }>('/me/library/state', { source_kind: target.source_kind, target_id: target.target_id }) }
export function saveFavorite(target: LibraryTarget, saved: boolean) { return post<{ saved: boolean }>('/me/library/favorite', { ...target, saved }) }
// Keep rapid selections in order even when a detail page is left or remounted.
const readingWrites = new Map<string, Promise<{ recorded: boolean }>>()
export function rememberReading(target: LibraryTarget, clause_id?: string) {
  const key = target.source_kind + ':' + target.target_id
  const token = localStorage.getItem('zg_token')
  const previous = readingWrites.get(key) || Promise.resolve()
  const write = previous.catch(() => undefined).then(() => {
    if (localStorage.getItem('zg_token') !== token) throw new Error('账号已变化，阅读记录未保存')
    return post<{ recorded: boolean }>('/me/library/reading', { ...target, clause_id: clause_id || null })
  })
  readingWrites.set(key, write)
  const clean = () => { if (readingWrites.get(key) === write) readingWrites.delete(key) }
  void write.then(clean, clean)
  return write
}
export function removeAnswerFavorite(session_id: string) { return post<{ saved: boolean }>('/me/library/answer-favorites/remove', { session_id }) }
