import { post, get } from './request'

export interface UserInfo {
  user_id: string
  username: string
  role: string
  org_id?: string | null
  post?: string | null
  secret_clearance: string
  permissions?: Array<{ role: string; org_scope: string; secret_level: string; domain: string }>
}

export interface DemoIdentity {
  username: string
  password: string
  role: string
  role_label: string
  post: string
  description: string
}

export interface DemoIdentityResponse {
  enabled: boolean
  identities: DemoIdentity[]
}

export function login(username: string, password: string) {
  return post<{ access_token: string; token_type: string; user: UserInfo }>('/auth/login', {
    username,
    password,
  })
}

export function me() {
  return get<UserInfo>('/auth/me')
}

export function demoIdentities() {
  return get<DemoIdentityResponse>('/auth/demo-identities')
}
