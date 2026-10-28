<template>
  <div class="zg-container notification-page" v-loading="push.loading">
    <PageHeader title="更新通知" description="阅读制度更新，查看相关依据，并留下个人阅读回执。"><template #actions><span class="hint">我的未读 {{ push.center ? ownUnread : '未读取' }} 条</span><el-button @click="load">刷新</el-button></template></PageHeader>
    <DataState :error="error" :empty="!push.loading && !push.center?.pushes.length" empty-title="暂无更新通知" empty-description="有新的制度通知时会出现在这里。你可以先查阅现行制度。" @retry="load">
      <template #actions><router-link to="/library">查阅制度</router-link></template>
      <div class="table-toolbar"><el-input v-model="keyword" clearable placeholder="搜索通知内容" class="keyword-input" aria-label="搜索通知内容"/><el-radio-group v-model="scope"><el-radio-button value="mine">发给我的</el-radio-button><el-radio-button value="unread">我的未读</el-radio-button><el-radio-button v-if="canViewLedger" value="all">通知台账</el-radio-button></el-radio-group><span class="hint">{{ filtered.length }} 条</span></div>
      <el-table :data="pageRows" border @row-click="open" empty-text="没有符合筛选条件的通知"><el-table-column label="通知内容" min-width="360"><template #default="{ row }"><el-button link type="primary" class="digest-link" @click.stop="open(row)">{{ row.digest || '制度更新通知' }}</el-button><div class="row-subtitle">{{ row.scenario_tag || '制度更新' }}</div></template></el-table-column><el-table-column label="我的阅读" width="115"><template #default="{ row }"><span :class="{ unread: row.unread_count > 0 }">{{ receiptLabel(row) }}</span></template></el-table-column><el-table-column label="发布时间" width="170"><template #default="{ row }">{{ time(row.push_time) }}</template></el-table-column><el-table-column label="发布状态" width="110"><template #default="{ row }">{{ statusLabel(row.status) }}</template></el-table-column></el-table>
      <div class="pager"><span class="hint">阅读回执只记录本人阅读，后续事项落实请进入变更影响。</span><el-pagination v-model:current-page="page" :page-size="20" layout="total, prev, pager, next" :total="filtered.length"/></div>
    </DataState>
    <el-drawer v-model="visible" title="通知详情" size="min(700px, 92vw)"><template v-if="selected"><div class="notice-meta"><span>{{ statusLabel(selected.status) }}</span><span>{{ time(selected.push_time) }}</span><span>{{ receiptLabel(selected) }}</span></div><h2>更新内容</h2><p class="notice-body">{{ selected.digest || '暂无摘要，请查看相关制度原文。' }}</p><dl class="notice-fields"><dt>业务场景</dt><dd>{{ selected.scenario_tag || '未标注' }}</dd><dt>接收范围</dt><dd>{{ roleLabel(selected.target_role) }}</dd></dl><div class="related-links"><router-link v-if="selected.file_id" :to="`/library/${selected.file_id}`">查看相关制度</router-link><router-link v-if="canViewLedger" to="/impact">查看变更影响</router-link></div><p class="hint">确认阅读表示已知悉本通知；事项复核和规则调整需要分别处理。</p><el-alert v-if="actionError" :title="actionError" type="error" :closable="false"/><div class="drawer-footer"><span>{{ selected.read_count > 0 ? '个人阅读回执已记录' : selected.unread_count > 0 ? '阅读后请确认' : '本通知未分配给你，无需提交回执' }}</span><el-button v-if="selected.status === 'sent' && selected.unread_count > 0" type="primary" :loading="saving" @click="confirmRead">确认已阅读</el-button></div></template></el-drawer>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { usePushStore } from '@/store/push'
import { useUserStore } from '@/store/user'
import type { PushRecordOut } from '@/api/push'
import * as pushApi from '@/api/push'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
const push = usePushStore(), user = useUserStore()
const route = useRoute()
const error = ref(''), actionError = ref(''), keyword = ref(''), scope = ref('mine'), page = ref(1), visible = ref(false), saving = ref(false)
const selected = ref<PushRecordOut | null>(null)
const ownUnread = computed(() => (push.center?.pushes || []).filter(item => item.status === 'sent' && item.unread_count > 0).length)
const canViewLedger = computed(() => ['R3', 'R4'].includes(user.role))
const filtered = computed(() => (push.center?.pushes || []).filter((item) => (scope.value === 'all' || (item.status === 'sent' && (scope.value === 'unread' ? item.unread_count > 0 : item.read_count + item.unread_count > 0))) && (!keyword.value.trim() || item.digest.toLowerCase().includes(keyword.value.trim().toLowerCase()))))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * 20, page.value * 20))
watch([keyword, scope], () => { page.value = 1 })
watch(() => route.query.filter, (value) => { scope.value = value === 'unread' ? 'unread' : 'mine' }, { immediate: true })
const receiptLabel = (row: PushRecordOut) => row.unread_count > 0 ? '未读' : row.read_count > 0 ? '已读' : '非本人接收'
const statusLabel = (status: string) => ({ draft: '草稿', pending_review: '待审核', sent: '已发布', recalled: '已撤回' } as Record<string, string>)[status] || status
const roleLabel = (role: string | null) => ({ R1: '员工', R2: '业务审核', R3: '制度管理', R4: '系统管理' } as Record<string, string>)[role || ''] || role || '按通知分配'
function time(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '未发布' }
function open(row: PushRecordOut) { if (saving.value) return; selected.value = row; actionError.value = ''; visible.value = true }
let loadingPromise: Promise<void> | null = null
async function load() {
  if (loadingPromise) return loadingPromise
  error.value = ''
  loadingPromise = push.load().then(() => { if (selected.value) selected.value = push.center?.pushes.find(item => item.push_id === selected.value?.push_id) || selected.value }).catch(() => { error.value = '通知暂时无法读取，请重试。' }).finally(() => { loadingPromise = null })
  return loadingPromise
}
async function confirmRead() {
  if (!selected.value || selected.value.status !== 'sent' || !selected.value.unread_count || saving.value) return
  const id = selected.value.push_id
  saving.value = true; actionError.value = ''
  try {
    await pushApi.markRead(id, true)
    const row = push.center?.pushes.find(item => item.push_id === id)
    if (row) { row.read_count = 1; row.unread_count = 0 }
    if (selected.value?.push_id === id) selected.value = row || { ...selected.value, read_count: 1, unread_count: 0 }
    ElMessage.success('已记录个人阅读回执')
    try { await push.load(); if (selected.value?.push_id === id) selected.value = push.center?.pushes.find(item => item.push_id === id) || selected.value }
    catch { actionError.value = '个人阅读回执已保存，但列表刷新失败。请刷新通知核对最新状态。' }
  } catch { actionError.value = '阅读回执未保存，请重试。' } finally { saving.value = false }
}
onMounted(load)
</script>
<style scoped>
.table-toolbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:16px 0}.keyword-input{max-width:320px}.row-subtitle{color:var(--zg-text-secondary);font-size:12px;margin-top:6px}.digest-link{white-space:normal;text-align:left;height:auto;line-height:1.6}.unread{color:var(--zg-primary);font-weight:600}.pager,.drawer-footer{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px;margin-top:18px}.notice-meta,.related-links{display:flex;flex-wrap:wrap;gap:16px;color:var(--zg-text-secondary);font-size:12px}.notice-body{overflow-wrap:anywhere;white-space:pre-wrap;line-height:1.9}.notice-fields{display:grid;grid-template-columns:90px minmax(0,1fr);gap:12px;margin:24px 0}.notice-fields dt{color:var(--zg-text-secondary)}.notice-fields dd{margin:0;overflow-wrap:anywhere}.drawer-footer{border-top:1px solid var(--zg-border);padding-top:16px;font-size:12px}h2{font-size:17px;margin-top:24px}@media(max-width:700px){.pager{flex-wrap:wrap}.keyword-input{max-width:100%}}
</style>
