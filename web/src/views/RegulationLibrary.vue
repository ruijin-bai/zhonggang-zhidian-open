<template>
  <div class="zg-container library-page" v-loading="loading">
    <PageHeader title="制度目录" description="查找制度、收藏常用资料，或从上次阅读的位置继续。"><template #actions><el-button @click="refresh">刷新</el-button></template></PageHeader>
    <el-tabs v-model="view"><el-tab-pane label="全部制度" name="all"/><el-tab-pane label="我的收藏" name="favorites"/><el-tab-pane label="最近阅读" name="recent"/></el-tabs>
    <PersonalLibraryPanel v-if="view !== 'all'" ref="personalPanel" :view="view"/>
    <div v-else class="library-layout">
      <aside class="category-panel work-panel" aria-label="制度分类">
        <div class="panel-head">按分类查找</div>
        <button type="button" :class="{ selected: !categoryFilter }" @click="categoryFilter = ''">全部制度<span>{{ rows.length }}</span></button>
        <button v-for="category in categories" :key="category.name" type="button" :class="{ selected: categoryFilter === category.name }" @click="categoryFilter = category.name">{{ category.name }}<span>{{ category.count }}</span></button>
      </aside>
      <section class="library-results">
        <div class="toolbar">
          <el-input v-model="keyword" clearable placeholder="搜索制度名、文号或来源" class="keyword-input" aria-label="搜索制度" />
          <el-select v-model="statusFilter" class="status-filter" aria-label="制度状态"><el-option label="全部状态" value="" /><el-option v-for="value in availableStatuses" :key="value" :label="statusName(value)" :value="value" /></el-select>
          <el-select v-model="authorityFilter" class="authority-filter" aria-label="来源确认"><el-option label="全部来源" value="" /><el-option label="来源已确认" value="verified" /><el-option label="来源待确认" value="pending" /></el-select>
          <span class="result-count">{{ loaded ? filteredRows.length + ' 份' : '正在加载' }}</span>
        </div>
        <DataState :error="error" :empty="loaded && !filteredRows.length" empty-title="没有匹配的制度" empty-description="换一个关键词或清除筛选条件后再查找。" @retry="load"><template #actions><el-button @click="clearFilters">清除筛选</el-button></template>
          <el-table :data="pageRows" border size="small" highlight-current-row @row-click="openDetail" class="directory-table">
            <el-table-column label="制度名称 / 文号" min-width="280"><template #default="{ row }"><button class="table-link" @click.stop="openDetail(row)">{{ row.title }}</button><div class="row-subline">{{ row.regulation_code || '未记录文号' }}</div></template></el-table-column>
            <el-table-column label="分类" min-width="130"><template #default="{ row }"><span>{{ (row.tags || []).join('、') || '未分类' }}</span></template></el-table-column>
            <el-table-column label="版本 / 状态" width="115"><template #default="{ row }"><div>{{ row.version }}</div><span class="row-subline">{{ statusName(row.status) }}</span></template></el-table-column>
            <el-table-column label="来源" min-width="170"><template #default="{ row }"><span :class="row.authority_verified ? 'verified' : 'pending'">{{ sourceLabel(row) }}</span></template></el-table-column>
            <el-table-column label="生效日期" width="115"><template #default="{ row }">{{ row.effective_date || '未记录' }}</template></el-table-column>
          </el-table>
          <div class="pagination-bar"><span>第 {{ page }} 页，共 {{ filteredRows.length }} 份；仅列当前账号可查看资料。</span><el-pagination v-model:current-page="page" :page-size="pageSize" :total="filteredRows.length" layout="prev, pager, next" /></div>
        </DataState>
        <p class="directory-note">筛选与页码会保留在地址中，进入详情后可原路返回。来源确认不代表事项已获审批，办理时仍需核对适用条件。</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as regulationApi from '@/api/regulation'
import * as assetApi from '@/api/asset'
import type { RegulationRow } from '@/api/regulation'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
import PersonalLibraryPanel from '@/components/PersonalLibraryPanel.vue'
import { statusName, errorText } from '@/utils/presentation'
const route = useRoute(), router = useRouter()
const loading = ref(false), loaded = ref(false), error = ref('')
const rows = ref<RegulationRow[]>([]), categories = ref<{ name: string; count: number }[]>([])
const keyword = ref(''), statusFilter = ref(''), categoryFilter = ref(''), authorityFilter = ref('')
const page = ref(1), pageSize = 15
const view = ref('all'), personalPanel = ref<{refresh:()=>Promise<void>} | null>(null)
let applyingQuery = false, queryTimer: ReturnType<typeof setTimeout> | undefined
const availableStatuses = computed(() => [...new Set(rows.value.map(row => row.status))])
const filteredRows = computed(() => {
  const term = keyword.value.trim().toLowerCase()
  return rows.value.filter(row => (!statusFilter.value || row.status === statusFilter.value) && (!categoryFilter.value || (row.tags || []).includes(categoryFilter.value)) && (!authorityFilter.value || row.authority_verified === (authorityFilter.value === 'verified')) && (!term || [row.title, row.regulation_code, row.source, row.version].filter(Boolean).join(' ').toLowerCase().includes(term)))
})
const pageRows = computed(() => filteredRows.value.slice((page.value - 1) * pageSize, page.value * pageSize))
function syncQuery() {
  if(applyingQuery || route.path!=='/library') return
  const query = {...route.query,q:keyword.value || undefined,status:statusFilter.value || undefined,category:categoryFilter.value || undefined,authority:authorityFilter.value || undefined,page:page.value>1 ? String(page.value) : undefined,view:view.value==='all' ? undefined : view.value}
  void router.replace({path:'/library',query})
}
watch([keyword, statusFilter, categoryFilter, authorityFilter], () => { if(applyingQuery) return; applyingQuery=true; page.value=1; applyingQuery=false; if(queryTimer) clearTimeout(queryTimer); queryTimer=setTimeout(syncQuery,250) }, {flush:'sync'})
watch([page,view], syncQuery, {flush:'sync'})
watch(() => route.query, query => {
  if(route.path!=='/library') return
  if (typeof query.file_id === 'string') { const {file_id,...rest}=query;void router.replace({ path: '/library/' + encodeURIComponent(file_id),query:rest }); return }
  applyingQuery=true
  keyword.value = typeof query.q === 'string' ? query.q : ''
  statusFilter.value=typeof query.status==='string' ? query.status : ''
  categoryFilter.value=typeof query.category==='string' ? query.category : ''
  authorityFilter.value=['verified','pending'].includes(String(query.authority)) ? String(query.authority) : ''
  page.value=typeof query.page==='string' && /^[1-9]\d*$/.test(query.page) ? Math.min(Number(query.page),100000) : 1
  view.value=['favorites','recent'].includes(String(query.view)) ? String(query.view) : 'all'
  applyingQuery=false
}, { immediate: true })
function clearFilters() { applyingQuery=true; keyword.value='';statusFilter.value='';categoryFilter.value='';authorityFilter.value='';page.value=1;applyingQuery=false;if(queryTimer) clearTimeout(queryTimer);syncQuery() }
function sourceLabel(row: RegulationRow) { return row.source_verification==='maintainer' ? '维护者已确认来源' : row.source_verification==='metadata' || row.authority_verified ? '来源信息已补齐' : '来源待确认' }
function openDetail(row: RegulationRow) { if(queryTimer) clearTimeout(queryTimer); const from=router.resolve({path:'/library',query:{...route.query,q:keyword.value || undefined,status:statusFilter.value || undefined,category:categoryFilter.value || undefined,authority:authorityFilter.value || undefined,page:page.value>1 ? String(page.value):undefined}}).fullPath; router.push({path:'/library/'+encodeURIComponent(row.file_id),query:{from,...(row.source_kind==='asset' ? {source:'asset',version:row.asset_version_id} : {})}}) }
function refresh() { return view.value==='all' ? load() : personalPanel.value?.refresh() }
type DirectoryAsset = assetApi.AssetRow & {readable_unit_count?:number}
function directoryCandidates(legacy:RegulationRow[], assets:DirectoryAsset[]) {
  const canonical = new Set(legacy.filter(row=>row.status==='current' && (row.clause_count===undefined || row.clause_count>0)).map(row=>row.file_id))
  return assets.filter(row=>row.release_state==='current' && row.ingestion_state==='ready' && (!row.legacy_file_id || !canonical.has(row.legacy_file_id)))
}
function mergeDirectory(legacy:RegulationRow[], assets:DirectoryAsset[]):RegulationRow[] {
  const candidates=directoryCandidates(legacy,assets).filter(row=>!row.legacy_file_id || (row.readable_unit_count ?? 0)>0)
  const replacedEmpty = new Set(candidates.filter(row=>row.legacy_file_id && (row.readable_unit_count ?? 0)>0).map(row=>row.legacy_file_id))
  const sourceRows = candidates.map(a=>{
    const source=a as assetApi.AssetRow & {domain?:string;org_path?:string;owner_org?:string}
    return {source_kind:'asset' as const,asset_version_id:a.version_id,file_id:a.asset_id,title:a.title,source:'已发布资料',version:a.version_label,status:a.release_state,regulation_code:a.issue_no || a.business_code,secret_level:a.secret_level,domain:source.domain || '*',org_path:source.org_path || '/',owner_org:source.owner_org,effective_date:a.effective_date,authority_verified:source.authority_verified===true,source_verification:source.source_verification,authority_gaps:source.authority_gaps || [],tags:[source.domain && source.domain!=='*' ? source.domain : '未分类'],has_original:false,document_count:a.document_count}
  })
  return [...legacy.filter(row=>row.clause_count!==0 || !replacedEmpty.has(row.file_id)),...sourceRows]
}
let request = 0
async function load() {
  const id = ++request
  loading.value = true; error.value = ''
  try {
    const [legacy, assets] = await Promise.all([regulationApi.listRegulations(), assetApi.list({published_only:true})])
    if (id !== request) return
    rows.value=mergeDirectory(legacy,assets)
    const counts = new Map<string, number>(); for (const row of rows.value) for (const tag of row.tags || []) counts.set(tag, (counts.get(tag) || 0) + 1)
    categories.value = [...counts].map(([name,count]) => ({name,count})).sort((a,b) => b.count-a.count || a.name.localeCompare(b.name))
    loaded.value = true
    if(page.value>Math.max(1,Math.ceil(filteredRows.value.length/pageSize))) page.value=Math.max(1,Math.ceil(filteredRows.value.length/pageSize))
  }
  catch (e) { if (id===request) { error.value = errorText(e); loaded.value = false } }
  finally { if (id===request) loading.value = false }
}
onMounted(load)
onBeforeUnmount(()=>{++request;if(queryTimer) clearTimeout(queryTimer)})
</script>

<style scoped>
.library-layout { display: grid; grid-template-columns: 185px minmax(0, 1fr); gap: 20px; align-items: start; }.category-panel button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; min-height: 39px; padding: 10px 14px; border: 0; border-bottom: 1px solid var(--zg-border-light); background: #fff; color: var(--zg-text-secondary); text-align: left; cursor: pointer; font-size: 12px; }.category-panel button.selected { background: var(--zg-primary-soft); color: var(--zg-primary); font-weight: 600; }.category-panel button:hover { background: var(--zg-panel-soft); }.category-panel span { font-size: 11px; font-weight: 400; }.category-panel .panel-head { padding: 14px; }.library-results { min-width: 0; }.keyword-input { flex: 1; min-width: 200px; }.status-filter { width: 120px; }.authority-filter { width: 140px; }.result-count { min-width: 46px; color: var(--zg-text-secondary); font-size: 12px; }.row-subline { margin-top: 5px; color: var(--zg-text-secondary); font-size: 11px; }.verified { color: #397553; }.pending { color: #946713; }.directory-note { color: var(--zg-text-secondary); font-size: 12px; line-height: 1.8; }.directory-table :deep(.el-table__body tr) { cursor: pointer; }
@media (max-width: 1050px) { .library-layout { grid-template-columns: 150px minmax(0, 1fr); } }
@media (max-width: 760px) { .library-layout { grid-template-columns: 1fr; }.category-panel { display: flex; max-height: 160px; overflow: auto; flex-wrap: wrap; }.category-panel .panel-head { width: 100%; min-height: 36px; padding: 8px 12px; }.category-panel button { width: auto; gap: 6px; min-height: 34px; }.status-filter, .authority-filter { flex: 1; min-width: 130px; }.keyword-input { flex-basis: 100%; } }
</style>
