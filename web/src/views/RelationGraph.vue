<template>
  <div class="zg-container" v-loading="loading">
    <PageHeader title="制度关系" description="核对制度之间的替代、从属与共同约束，沿关系查看完整制度。"><template #actions><el-button @click="load">刷新</el-button></template></PageHeader>
    <DataState :error="error" :empty="!loading && !!data && !data.edges.length" empty-title="尚未建立制度关系" empty-description="可以先在制度目录查阅原件。制度管理人员确认关系后，关联制度会出现在这里。" @retry="load"><template #actions><router-link to="/library">查阅制度目录</router-link></template>
      <div v-if="data?.conflicts.length" class="conflict-note">存在 {{ data.conflicts.length }} 条冲突关系。办理前请核对制度版本和责任部门确认的适用口径。<el-button link type="primary" @click="typeFilter = 'conflict'; view = 'list'">查看冲突</el-button></div>
      <el-tabs v-model="view"><el-tab-pane label="关系清单" name="list"><div class="table-toolbar"><el-input v-model="keyword" clearable placeholder="搜索制度名称、版本或关系说明" class="keyword-input" aria-label="搜索制度关系"/><el-select v-model="typeFilter" aria-label="关系类型" style="width:150px"><el-option label="全部关系" value=""/><el-option v-for="item in relationTypes" :key="item.value" :label="item.label" :value="item.value"/></el-select><span class="hint">{{ filteredRows.length }} 条</span></div>
        <el-table :data="filteredRows" border empty-text="没有符合筛选条件的关系"><el-table-column label="制度" min-width="260"><template #default="{ row }"><router-link :to="`/library/${row.from}`">{{ row.fromTitle }}</router-link><div class="row-note">{{ row.fromVersion || '版本未标注' }} · {{ statusLabel(row.fromStatus) }}</div></template></el-table-column><el-table-column label="关联方式" width="140"><template #default="{ row }"><b :class="{ conflict: row.type === 'conflict' }">{{ row.typeLabel }}</b></template></el-table-column><el-table-column label="关联制度" min-width="260"><template #default="{ row }"><router-link :to="`/library/${row.to}`">{{ row.toTitle }}</router-link><div class="row-note">{{ row.toVersion || '版本未标注' }} · {{ statusLabel(row.toStatus) }}</div></template></el-table-column><el-table-column label="适用说明" min-width="320"><template #default="{ row }"><p class="relation-note">{{ row.note || '尚无说明，请核对原件后确认适用关系。' }}</p><span class="row-note">{{ row.confirmed_by ? '已登记关系确认人' : '尚未登记确认人' }}</span></template></el-table-column></el-table>
        <p class="hint relation-help">关系按“左侧制度 → 右侧制度”读取。替代关系表示左侧版本替代右侧；从属关系表示左侧制度从属于右侧。具体适用以原件和确认说明为准。</p>
      </el-tab-pane><el-tab-pane label="关联范围图" name="graph"><p class="hint">拖动与缩放可查看关联范围。核对版本和说明时请使用关系清单。</p><RelationGraphChart v-if="data && view === 'graph'" :data="data"/></el-tab-pane></el-tabs>
    </DataState>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import * as relationApi from '@/api/relation'
import type { GraphData } from '@/api/relation'
import RelationGraphChart from '@/components/RelationGraphChart.vue'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
const loading = ref(false), error = ref(''), view = ref('list'), keyword = ref(''), typeFilter = ref('')
const data = ref<GraphData | null>(null)
const relationTypes = [{ value: 'replace', label: '替代' }, { value: 'subordinate', label: '从属' }, { value: 'multi_constraint', label: '共同约束' }, { value: 'conflict', label: '冲突' }]
const relationRows = computed(() => { const files = new Map(data.value?.nodes.map((node) => [node.id, node]) || []); return (data.value?.edges || []).map((edge) => ({ ...edge, fromTitle: files.get(edge.from)?.title || '制度未返回', fromVersion: files.get(edge.from)?.version, fromStatus: files.get(edge.from)?.status, toTitle: files.get(edge.to)?.title || '制度未返回', toVersion: files.get(edge.to)?.version, toStatus: files.get(edge.to)?.status, typeLabel: relationTypes.find((item) => item.value === edge.type)?.label || edge.type_label || edge.type })) })
const filteredRows = computed(() => { const term = keyword.value.trim().toLowerCase(); return relationRows.value.filter((row) => (!typeFilter.value || row.type === typeFilter.value) && (!term || [row.fromTitle, row.fromVersion, row.toTitle, row.toVersion, row.note].filter(Boolean).join(' ').toLowerCase().includes(term))) })
const statusLabel = (status?: string) => ({ current: '现行', replaced: '已替代', repealed: '已废止', pending_review: '待审核', draft: '草稿' } as Record<string, string>)[status || ''] || '状态待核对'
async function load() { if (loading.value) return; loading.value = true; error.value = ''; try { data.value = await relationApi.graph() } catch { error.value = '制度关系读取失败，请重试。' } finally { loading.value = false } }
onMounted(load)
</script>
<style scoped>
.table-toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}.keyword-input{max-width:360px}.row-note{color:var(--zg-text-secondary);font-size:12px;line-height:1.7;margin-top:5px}.relation-note{margin:0;line-height:1.7}.conflict,.conflict-note{color:#8a4c00}.conflict-note{display:flex;flex-wrap:wrap;align-items:center;gap:12px;border-bottom:1px solid var(--zg-border);padding:12px 0;margin-bottom:16px;line-height:1.7;font-size:13px}.relation-help{margin:16px 0;line-height:1.8}
</style>
