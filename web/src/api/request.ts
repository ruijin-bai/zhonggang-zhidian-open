import axios, { type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

/** Unified envelope returned by the backend. */
export interface Envelope<T = unknown> {
  code: number
  message: string
  data: T
  trace_id: string
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 20000,
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('zg_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

request.interceptors.response.use(
  (resp) => {
    const body = resp.data as Envelope
    if (body && typeof body.code === 'number' && body.code !== 0) {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    if (resp.config.method && !['get', 'head', 'options'].includes(resp.config.method.toLowerCase())) window.dispatchEvent(new Event('zg-workbench-changed'))
    return body?.data as unknown as AxiosResponse
  },
  (error) => {
    if (axios.isCancel(error)) return Promise.reject(error)
    const status = error.response?.status
    const body = error.response?.data
    if (status === 401) {
      localStorage.removeItem('zg_token')
      localStorage.removeItem('zg_role')
      if (location.pathname !== '/login') location.href = '/login?redirect=' + encodeURIComponent(location.pathname + location.search + location.hash)
    }
    const msg = body?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

export async function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request.get(url, { params }) as unknown as Promise<T>
}
export async function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request.post(url, data, config) as unknown as Promise<T>
}
export async function put<T>(url: string, data?: unknown): Promise<T> {
  return request.put(url, data) as unknown as Promise<T>
}
export async function del<T>(url: string): Promise<T> {
  return request.delete(url) as unknown as Promise<T>
}

export default request
