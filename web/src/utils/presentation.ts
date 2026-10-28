export const roleNames: Record<string, string> = {
  R1: '员工', R2: '审核人员', R3: '知识管理员', R4: '系统管理员',
}

export const statusNames: Record<string, string> = {
  current: '现行', published: '已发布', processing: '处理中', pending: '待处理',
  pending_review: '待审核', rejected: '已退回', failed: '处理失败',
  replaced: '已替代', repealed: '已废止', draft: '草稿', approved: '已审核',
  isolated: '已隔离', completed: '已完成', ready: '已就绪',
}

export function statusName(value: string) { return statusNames[value] || value || '未记录' }

export function sourceLocation(locator?: string | null, page?: number | null): string {
  const value = locator || ''
  const pageMatch = value.match(/^page:(\d+)(?:\/article:(\d+))?$/)
  if (pageMatch) return `原件第 ${pageMatch[1]} 页${pageMatch[2] ? ` · 条款 ${pageMatch[2]}` : ''}`
  const paragraph = value.match(/^(?:paragraph:(\d+)|word:\/document\/body\/p\[(\d+)\])$/)
  if (paragraph) return `原文第 ${paragraph[1] || paragraph[2]} 段`
  const sheet = value.match(/^sheet:(.*);row:(\d+)$/) || value.match(/^excel:\/sheet\/(.+)\/row\/(\d+)$/)
  if (sheet) return `工作表「${sheet[1]}」第 ${sheet[2]} 行`
  const cell = value.match(/^excel:\/sheet\/(.+)\/cell\/(.+)$/)
  if (cell) return `工作表「${cell[1]}」单元格 ${cell[2]}`
  const slide = value.match(/^pptx:\/slides\/slide(\d+)$/)
  if (slide) return `原件第 ${slide[1]} 张幻灯片`
  if (page) return `原件第 ${page} 页`
  return value ? '原件结构位置已记录' : '原件位置未记录'
}

export function errorText(error: unknown, fallback = '请检查服务是否可用后重试。'): string {
  if (error instanceof Error && error.message && !/status code/i.test(error.message)) return error.message
  return fallback
}
