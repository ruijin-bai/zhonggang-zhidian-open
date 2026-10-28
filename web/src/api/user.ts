import { post, get } from './request'

export interface UserOut {
  user_id: string
  username: string
  role: string
  org_id: string | null
  post: string | null
  secret_clearance: string
  is_active: boolean
}

export function listUsers() {
  return get<UserOut[]>('/users')
}
export function createUser(body: { username: string; password: string; role: string; org_id?: string; post?: string; secret_clearance?: string }) {
  return post('/users', body)
}
