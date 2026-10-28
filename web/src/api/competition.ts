import { get } from './request'

export function evidence() {
  return get<any>('/competition/evidence')
}
