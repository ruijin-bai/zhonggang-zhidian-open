<template>
  <div class="zg-container" v-loading="loading">
    <PageHeader title="变更影响" description="制度发布新版本后，核对变化、调整规则并复核历史事项。"><template #actions><el-button @click="load">刷新</el-button></template></PageHeader>
    <DataState :error="error" :empty="!loading && !runs.length" empty-title="暂无版本变更记录" empty-description="制度替代版本发布后，这里会列出受影响的条款、办理规则与事项。" @retry="load"><template #actions><router-link to="/library">查阅现行制度</router-link></template>
      <div class="impact-toolbar"><el-input v-model="keyword" clearable placeholder="搜索制度名称" aria-label="搜索变更制度" style="max-width:320px"/><el-radio-group v-model="status"><el-radio-button value="">全部</el-radio-button><el-radio-button value="draft">待处理</el-radio-button><el-radio-button value="confirmed">已确认</el-radio-button></el-radio-group><span class="hint">{{ filteredRuns.length }} 份变更</span></div>
      <el-table :data="filteredRuns" border @row-click="open" empty-text="没有符合筛选条件的变更"><el-table-column label="版本变化" min-width="330"><template #default="{ row }"><el-button link type="primary" @click.stop="open(row)">{{ row.new_file_title }}</el-button><div class="row-note">{{ row.old_file_version || '首次版本' }} → {{ row.new_file_version || '未标注版本' }}</div></template></el-table-column><el-table-column label="条款变化" width="100" align="right"><template #default="{ row }">{{ clauseDiffCount(row) }}</template></el-table-column><el-table-column label="规则需调整" width="110" align="right"><template #default="{ row }">{{ row.summary.rule_rebuild_required || 0 }}</template></el-table-column><el-table-column label="事项需复核" width="110" align="right"><template #default="{ row }">{{ row.summary.historical_case_review || 0 }}</template></el-table-column><el-table-column label="高风险待处理" width="125" align="right"><template #default="{ row }"><b :class="{ high: highOpenCount(row) > 0 }">{{ highOpenCount(row) }}</b></template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }">{{ row.status === 'confirmed' ? '已确认' : '待处理' }}</template></el-table-column></el-table>
    </DataState>
    <el-drawer v-model="detailVisible" size="min(1000px, 96vw)" title="核对与处理变更" :before-close="closeDrawer">
      <div v-loading="detailLoading"><DataState :error="detailError" @retry="reloadDetail"><template v-if="detail"><h2>{{ detail.new_file_title }}</h2><div class="version-line"><router-link v-if="detail.old_file_id" :to="`/library/${detail.old_file_id}`">原版本 {{ detail.old_file_version }}</router-link><span>→</span><router-link :to="`/library/${detail.new_file_id}`">新版本 {{ detail.new_file_version }}</router-link><el-tag effect="plain">{{ detail.status === 'confirmed' ? '已确认' : '待处理' }}</el-tag></div>
        <p v-if="openHighItems > 0" class="risk-note">还有 {{ openHighItems }} 项高风险未处理。请先完成实际调整并记录结果，再确认本次影响已落实。</p>
        <el-tabs v-model="detailTab"><el-tab-pane :label="`待处理 ${pendingItems.length}`" name="pending"/><el-tab-pane :label="`全部 ${detail.items?.length || 0}`" name="all"/></el-tabs>
        <el-table :data="displayItems" border @row-click="selectItem" empty-text="没有待处理的影响项"><el-table-column label="影响内容" min-width="280"><template #default="{ row }"><el-button link type="primary" @click.stop="selectItem(row)">{{ itemType(row.item_type) }}</el-button><div class="row-note">{{ snapshotText(row.new_snapshot) }}</div></template></el-table-column><el-table-column label="对象" width="110"><template #default="{ row }">{{ objectType(row.object_type) }}</template></el-table-column><el-table-column label="风险" width="85"><template #default="{ row }"><span :class="row.severity">{{ severityLabel(row.severity) }}</span></template></el-table-column><el-table-column label="处理状态" width="110"><template #default="{ row }">{{ row.status === 'resolved' ? '已处理' : '待处理' }}</template></el-table-column></el-table>
        <section v-if="selectedItem" class="item-detail"><h3>{{ itemType(selectedItem.item_type) }} <small>{{ severityLabel(selectedItem.severity) }}风险</small></h3><div class="snapshot-grid"><div><h4>原口径</h4><p>{{ snapshotText(selectedItem.old_snapshot) }}</p></div><div><h4>新口径与处理要求</h4><p>{{ snapshotText(selectedItem.new_snapshot) }}</p></div></div><div class="object-links"><router-link v-if="selectedItem.object_type === 'clause' && selectedItem.object_id" :to="`/clause/${selectedItem.object_id}`">查看条款</router-link><router-link v-if="selectedItem.object_type === 'decision_rule'" :to="selectedItem.object_id ? `/rules?id=${encodeURIComponent(selectedItem.object_id)}` : '/rules'">调整办理规则</router-link><router-link v-if="selectedItem.object_type === 'business_case' && canConfirm" :to="selectedItem.object_id ? `/case?id=${encodeURIComponent(selectedItem.object_id)}` : '/case'">复核办理事项</router-link><span v-else-if="selectedItem.object_type === 'business_case'" class="hint">请交业务审核人员复核相关事项</span></div>
          <template v-if="selectedItem.status === 'resolved'"><h4>处理记录</h4><p class="resolution">{{ selectedItem.resolution || '未返回处理说明' }}</p><span class="hint">{{ selectedItem.resolved_at ? new Date(selectedItem.resolved_at).toLocaleString('zh-CN') : '' }}</span></template><template v-else><h4>实际处理结果</h4><el-input v-model="resolution" :disabled="saving" type="textarea" :rows="3" placeholder="记录已完成的调整、复核结果和依据。仅保存说明不会自动重建规则或审批事项。"/><div class="item-actions"><el-button type="primary" :disabled="!resolution.trim()" :loading="saving" @click="resolve">保存处理记录</el-button></div></template>
        </section>
        <el-alert v-if="actionError" type="error" :title="actionError" :closable="false"/>
        <section v-if="detail.status !== 'confirmed' && canConfirm" class="confirm-section"><h3>确认变更落实</h3><p class="hint">高风险项需全部处理。确认会记录本次影响分析的闭环状态。</p><el-input v-model="confirmationNote" :disabled="saving" placeholder="确认说明（可选）"/><div class="item-actions"><el-button type="primary" :disabled="openHighItems > 0 || detailLoading || !!detailError" :loading="saving" @click="confirm">确认已落实</el-button></div></section><section v-else-if="detail.status === 'confirmed'" class="confirm-section"><h3>确认记录</h3><p>{{ detail.confirmation_note || '已确认，未补充说明。' }}</p></section><section v-else class="confirm-section"><h3>等待业务审核确认</h3><p class="hint">制度管理人员可记录影响项处理结果；高风险处置完成后，由业务审核或系统管理人员确认本次变更落实。</p></section>
      </template></DataState></div>
    </el-drawer>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onBeforeRouteLeave } from 'vue-router'
import { useUserStore } from '@/store/user'
import * as impactApi from '@/api/impact'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
const loading = ref(false), error = ref(''), keyword = ref(''), status = ref(''), detailVisible = ref(false), detailLoading = ref(false), detailError = ref(''), actionError = ref(''), detailTab = ref('pending'), resolution = ref(''), confirmationNote = ref(''), saving = ref(false)
const runs = ref<impactApi.ImpactRun[]>([]), detail = ref<impactApi.ImpactRun | null>(null), selectedItem = ref<impactApi.ImpactItem | null>(null)
const user = useUserStore()
const canConfirm = computed(() => ['R2', 'R4'].includes(user.role))
let detailVersion = 0
const filteredRuns = computed(() => runs.value.filter((row) => (!status.value || row.status === status.value) && (!keyword.value.trim() || row.new_file_title.includes(keyword.value.trim()))))
const pendingItems = computed(() => (detail.value?.items || []).filter((item) => item.status !== 'resolved'))
const displayItems = computed(() => detailTab.value === 'pending' ? pendingItems.value : detail.value?.items || [])
const openHighItems = computed(() => pendingItems.value.filter((item) => item.severity === 'high').length)
function clauseDiffCount(row: impactApi.ImpactRun) { return (row.summary.clause_changed || 0) + (row.summary.clause_added || 0) + (row.summary.clause_removed || 0) }
function highOpenCount(row: impactApi.ImpactRun) { return row.status === 'confirmed' ? 0 : row.summary.high_risk_open || 0 }
const itemType = (type: string) => ({ clause_changed: '条款内容变化', clause_added: '新增条款', clause_removed: '删除条款', rule_rebuild_required: '办理规则需调整', historical_case_review: '历史事项需复核' } as Record<string, string>)[type] || type
const objectType = (type: string) => ({ clause: '制度条款', decision_rule: '办理规则', business_case: '办理事项' } as Record<string, string>)[type] || type
const severityLabel = (level: string) => ({ high: '高', medium: '中', low: '低' } as Record<string, string>)[level] || level
function snapshotText(snapshot: Record<string, any>) { return snapshot.content || snapshot.action || snapshot.decision_summary || snapshot.rule_key || '无内容记录' }
async function selectItem(item: impactApi.ImpactItem) { if (saving.value || selectedItem.value?.item_id === item.item_id) return; if (resolution.value.trim()) { try { await ElMessageBox.confirm('当前处理说明尚未保存。切换后将丢失。', '切换影响项', { confirmButtonText: '放弃并切换', cancelButtonText: '继续编辑' }) } catch { return } }; selectedItem.value = item; resolution.value = ''; actionError.value = '' }
async function load() { if (loading.value) return; loading.value = true; error.value = ''; try { runs.value = await impactApi.listImpacts() } catch { error.value = '变更记录读取失败，请重试。' } finally { loading.value = false } }
async function discardEdits() {
  if (saving.value) return false
  if (!resolution.value.trim() && !confirmationNote.value.trim()) return true
  try { await ElMessageBox.confirm('当前处理说明或确认说明尚未保存，离开后将丢失。', '保留编辑', { confirmButtonText: '放弃并离开', cancelButtonText: '继续编辑' }); return true } catch { return false }
}
async function open(row: impactApi.ImpactRun) {
  if (saving.value || (detailVisible.value && !(await discardEdits()))) return
  detailVersion++; detail.value = row; selectedItem.value = null; resolution.value = ''; confirmationNote.value = ''; actionError.value = ''; detailTab.value = 'pending'; detailVisible.value = true
  await reloadDetail()
}
async function reloadDetail() {
  if (!detail.value) return
  const id = detail.value.impact_id, version = ++detailVersion
  detailLoading.value = true; detailError.value = ''
  try { const result = await impactApi.impactDetail(id); if (version === detailVersion && detailVisible.value) detail.value = result }
  catch { if (version === detailVersion && detailVisible.value) detailError.value = '影响明细读取失败，请重试。' }
  finally { if (version === detailVersion) detailLoading.value = false }
}
async function resolve() {
  if (!detail.value || !selectedItem.value || !resolution.value.trim() || saving.value) return
  const impactId = detail.value.impact_id, itemId = selectedItem.value.item_id, note = resolution.value.trim()
  saving.value = true; actionError.value = ''
  try {
    const saved = await impactApi.resolveImpactItem(impactId, itemId, note)
    detailVersion++
    detail.value.items = (detail.value.items || []).map(item => item.item_id === itemId ? saved : item)
    selectedItem.value = saved; resolution.value = ''; ElMessage.success('处理记录已保存')
    await reloadDetail(); await load()
  } catch { actionError.value = '处理记录未保存，请重试。' } finally { saving.value = false }
}
async function confirm() {
  if (!canConfirm.value || !detail.value || detailLoading.value || detailError.value || openHighItems.value || saving.value) return
  if (resolution.value.trim()) { actionError.value = '请先保存当前影响项的处理说明，再确认变更落实。'; return }
  const impactId = detail.value.impact_id
  const remaining = pendingItems.value.length ? `仍有${pendingItems.value.length}项中低风险记录未处理，确认不会将它们自动标为已处理。` : ''
  try { await ElMessageBox.confirm(`确认已核对影响清单并完成高风险处理？${remaining}`, '确认变更落实', { confirmButtonText: '确认已落实', cancelButtonText: '继续核对', type: 'warning' }) } catch { return }
  if (!detail.value || detail.value.impact_id !== impactId || saving.value) return
  saving.value = true; actionError.value = ''
  try { detail.value = await impactApi.confirmImpact(impactId, confirmationNote.value.trim()); detailVersion++; confirmationNote.value = ''; ElMessage.success('变更落实已确认'); await load() }
  catch { actionError.value = '确认未保存。请检查影响项是否仍有高风险未处理后重试。' } finally { saving.value = false }
}
async function closeDrawer(done: () => void) { if (await discardEdits()) { detailVersion++; detailLoading.value = false; resolution.value = ''; confirmationNote.value = ''; done() } }
onBeforeRouteLeave(async () => !detailVisible.value || await discardEdits())
onMounted(load)
</script>
<style scoped>
.impact-toolbar,.version-line,.object-links{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:16px 0}.row-note{font-size:12px;color:var(--zg-text-secondary);line-height:1.7;margin-top:5px}.high{color:#a33a2b}.medium,.risk-note{color:#8a5a00}.low{color:#397553}.risk-note{line-height:1.8;border-bottom:1px solid var(--zg-border);padding:12px 0}.item-detail,.confirm-section{margin-top:24px;border-top:1px solid var(--zg-border);padding-top:16px}h2{font-size:20px;margin:0 0 12px}h3{font-size:15px}h3 small{font-size:12px;margin-left:12px;color:var(--zg-text-secondary)}h4{font-size:13px;margin:12px 0}.snapshot-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.snapshot-grid p,.resolution{overflow-wrap:anywhere;white-space:pre-wrap;line-height:1.8;font-size:13px}.item-actions{display:flex;justify-content:flex-end;margin-top:12px}@media(max-width:700px){.snapshot-grid{grid-template-columns:minmax(0,1fr)}}
</style>
