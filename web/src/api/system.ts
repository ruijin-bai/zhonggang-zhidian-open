import { get, put, post } from './request'

/** 获取当前模型配置（api_key 已脱敏）。 */
export function getModelConfig() {
  return get<any>('/system/model-config')
}

/** 双模型连通性校验通过后，才保存并启用真实模型；api_key 留空表示沿用已存密钥。 */
export function saveModelConfig(data: Record<string, unknown>) {
  return put<any>('/system/model-config', data)
}

/** 用提交的配置实测一次 LLM + Embedding 连通性。 */
export function testModelConfig(data: Record<string, unknown>) {
  return post<any>('/system/model-config/test', data)
}

export function getCompetitionCapabilities() {
  return get<{ competition_demo_enabled: boolean }>('/system/competition-capabilities')
}
