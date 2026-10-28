<template>
  <div class="zg-container regulation-detail" v-loading="loading">
    <router-link class="back-link" :to="backTo">‹ 返回制度目录</router-link>
    <PageHeader :title="detail?.title || '制度详情'" :description="detail ? `${detail.version} · ${statusName(detail.status)}` : '加载制度正文与来源信息'">
      <template v-if="detail" #actions><el-button v-if="canSave" :loading="savingFavorite" :disabled="!personalReady || savingFavorite" @click="toggleFavorite">{{ saved ? '取消收藏' : '加入收藏' }}</el-button><el-button @click="consult">咨询这份制度</el-button><el-button v-if="detail.has_original" type="primary" :loading="downloading" @click="downloadOriginal">下载原件</el-button></template>
    </PageHeader>
    <DataState :error="error" @retry="load">
      <template v-if="detail">
        <p v-if="personalError" class="status-note source-note">{{ personalError }} <el-button text @click="loadPersonal(request)">重试个人记录</el-button></p>
        <p v-else-if="readingError" class="status-note source-note">{{ readingError }} <el-button text @click="recordPosition">重试保存阅读位置</el-button></p>
        <p v-else-if="resumed" class="reading-notice">已回到上次阅读的位置。</p>
        <div class="detail-layout">
          <section class="work-panel document-workspace">
            <el-tabs v-model="tab">
              <el-tab-pane label="正文阅读" name="content">
                <div class="reading-toolbar"><el-input v-model="contentQuery" clearable placeholder="在本制度中查找关键词" aria-label="查找正文" /><span>{{ filteredClauses.length }} 条<span v-if="isAsset && readerTotal > clauses.length"> / {{ readerTotal }} 条</span></span></div>
                <p v-if="readerError" class="status-note">{{ readerError }} <el-button text @click="loadAssetText(true)">重试读取</el-button></p>
                <DataState :empty="!clauses.length" empty-title="暂无可阅读的条款" empty-description="可以下载原件查看；资料尚未完成解析时，请联系知识管理员。">
                  <div class="reader-layout">
                    <aside class="content-index" aria-label="正文目录">
                      <el-select v-model="chapter" aria-label="筛选章节"><el-option label="全部章节" value="" /><el-option v-for="item in chapters" :key="item" :label="item" :value="item" /></el-select>
                      <div class="index-list"><button v-for="clause in visibleClauses" :key="clause.clause_id" type="button" :class="{ active: selected?.clause_id === clause.clause_id }" @click="selectClause(clause)"><strong>{{ clause.clause_no || '正文片段' }}</strong><small>{{ clause.content.slice(0, 56) }}</small></button></div>
                      <el-button v-if="filteredClauses.length > indexLimit" text @click="indexLimit += 40">继续显示目录</el-button>
                      <el-button v-else-if="isAsset && readerTotal > clauses.length" text :loading="readerLoading" @click="loadAssetText(false)">加载后续正文</el-button>
                      <p v-if="!filteredClauses.length" class="index-empty">没有匹配的正文。</p>
                    </aside>
                    <article v-if="selected" class="reading-article">
                      <div class="reading-header"><span v-if="selected.chapter" class="chapter-label">{{ selected.chapter }}</span><h2>{{ selected.clause_no || '正文' }}</h2><span class="locator">{{ sourceLocation(selected.source_locator, selected.source_page) }}</span></div>
                      <div class="reading-content"><p class="reading-text">{{ selected.content }}</p></div>
                      <div class="reading-footer"><router-link :to="`/clause/${selected.clause_id}`">打开引用详情</router-link><span>原文摘录，保留制度表述</span></div>
                    </article>
                    <div v-else class="data-state"><strong>选择一条正文开始阅读</strong></div>
                  </div>
                </DataState>
              </el-tab-pane>
              <el-tab-pane :label="`文件与附件（${documents.length}）`" name="files">
                <p class="files-note">正文、印发通知和附件分别保留；请核对文件角色后使用。</p>
                <DataState :empty="!documents.length" empty-title="未记录关联文件" empty-description="如有原件，可通过页首下载按钮查看。">
                  <el-table :data="documents" size="small" border><el-table-column label="文件" min-width="240"><template #default="{ row }">{{ row.filename || row.title }}</template></el-table-column><el-table-column label="用途" width="105"><template #default="{ row }">{{ docTypeName(row.doc_type) }}</template></el-table-column><el-table-column label="操作" width="95"><template #default="{ row }"><el-button text :loading="downloadingId === row.doc_id" @click="downloadAttachment(row)">下载</el-button></template></el-table-column></el-table>
                </DataState>
              </el-tab-pane>
              <el-tab-pane label="版本与来源" name="source">
                <p class="source-summary" :class="detail.authority_verified ? 'verified' : 'pending'">{{ sourceLabel }}<span v-if="!detail.authority_verified">。来源声明尚未确认，可阅读原文并联系维护者核对。</span></p>
                <p v-if="detail.authority_gaps?.length" class="files-note">可补充的来源信息：{{ gapLabels }}。<router-link v-if="canMaintain" :to="isAsset ? '/assets' : '/admin?tab=governance'">管理来源信息</router-link></p>
                <dl class="meta-list source-details"><div><dt>正式文号</dt><dd>{{ detail.regulation_code || '待补充' }}</dd></div><div><dt>发布来源</dt><dd>{{ detail.source || '待补充' }}</dd></div><div><dt>生效日期</dt><dd>{{ detail.effective_date || '待补充' }}</dd></div><div><dt>失效日期</dt><dd>{{ detail.expiry_date || '未记录' }}</dd></div><div><dt>审核时间</dt><dd>{{ formatDate(detail.reviewed_at) }}</dd></div><div><dt>审核说明</dt><dd>{{ detail.review_note || '未记录' }}</dd></div></dl>
                <div v-if="detail.replaces_file_id" class="related-version">本版本替代历史制度。<router-link :to="`/library/${detail.replaces_file_id}`">查看被替代版本</router-link></div>
              </el-tab-pane>
            </el-tabs>
          </section>
          <aside class="work-panel source-sidebar">
            <div class="panel-head">使用前核对</div>
            <div class="panel-body"><dl class="meta-list"><div><dt>制度状态</dt><dd>{{ statusName(detail.status) }}</dd></div><div><dt>来源确认</dt><dd :class="detail.authority_verified ? 'verified' : 'pending'">{{ sourceLabel }}</dd></div><div><dt>生效日期</dt><dd>{{ detail.effective_date || '未记录' }}</dd></div><div><dt>分类</dt><dd>{{ detail.tags?.filter(tag => tag && tag !== '*').join('、') || '未分类' }}</dd></div><div><dt>资料密级</dt><dd>{{ secretName(detail.secret_level) }}</dd></div></dl><p class="sidebar-note">资料可阅读不等于事项已获审批。办理时会核对规则、条件和有效依据。</p></div>
          </aside>
        </div>
      </template>
    </DataState>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/store/user'
import * as regApi from '@/api/regulation'
import * as assetApi from '@/api/asset'
import * as clauseApi from '@/api/clause'
import * as personalApi from '@/api/personalLibrary'
import type { LibraryTarget } from '@/api/personalLibrary'
import type { RegulationRow, ClauseRow } from '@/api/regulation'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
import { statusName, errorText, sourceLocation } from '@/utils/presentation'
const route = useRoute(), router = useRouter(), user = useUserStore()
const detail = ref<RegulationRow | null>(null), clauses = ref<ClauseRow[]>([]), loading = ref(false), error = ref('')
const tab = ref('content'), contentQuery = ref(''), chapter = ref(''), indexLimit = ref(40), selectedId = ref('')
const downloading = ref(false), downloadingId = ref('')
const saved=ref(false),personalReady=ref(false),savingFavorite=ref(false),personalError=ref(''),readingError=ref(''),resumed=ref(false)
const backTo=computed(()=>typeof route.query.from==='string' && /^\/library(?:\?|$)/.test(route.query.from) ? route.query.from : '/library')
const today=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}
const canSave=computed(()=>!!detail.value && detail.value.status==='current' && (!detail.value.effective_date || detail.value.effective_date<=today()) && (!detail.value.expiry_date || detail.value.expiry_date>=today()))
const sourceLabel=computed(()=>detail.value?.source_verification==='maintainer' ? '维护者已确认来源' : detail.value?.source_verification==='metadata' || detail.value?.authority_verified ? '来源信息已补齐' : '来源待确认')
const isAsset = computed(() => route.query.source === 'asset')
const readerTotal = ref(0), readerOffset = ref(0), readerLoading = ref(false), readerError = ref('')
const documents = computed(() => detail.value?.documents || [])
const canMaintain = computed(() => ['R3', 'R4'].includes(user.role))
const chapters = computed(() => [...new Set(clauses.value.map(c => c.chapter).filter((c): c is string => !!c))])
const filteredClauses = computed(() => clauses.value.filter(c => (!chapter.value || c.chapter === chapter.value) && (!contentQuery.value || [c.clause_no, c.chapter, c.content].join(' ').includes(contentQuery.value))))
const visibleClauses = computed(() => filteredClauses.value.slice(0, indexLimit.value))
const selected = computed(() => filteredClauses.value.find(c => c.clause_id === selectedId.value) || filteredClauses.value[0])
const gapLabels = computed(() => (detail.value?.authority_gaps || []).map(g => ({ regulation_code: '正式文号', issue_no: '正式文号', effective_date: '生效日期', owner_org: '责任部门', domain: '业务领域', source: '发布来源' }[g] || g)).join('、') || '正式来源信息')
function docTypeName(value: string) { return ({ main: '规范正文', normative_body:'规范正文',normative_annex:'规范附件',issuance_notice:'印发通知',standard_table:'标准表格',form:'业务表单',template:'业务模板',flowchart:'流程图',implementation_guide:'实施指引',reference:'参考资料',raw_asset:'原始素材', attachment: '附件', notice: '印发通知', history: '历史版本', review_opinion: '会审意见', training: '培训材料' }[value] || value) }
function secretName(value: string) { return ({ public: '公开', internal: '内部', confidential: '机密', secret: '秘密' }[value] || value) }
function formatDate(value?: string | null) { return value ? value.slice(0, 19).replace('T', ' ') : '未记录' }
function selectClause(clause: ClauseRow) { selectedId.value = clause.clause_id; resumed.value=false; void router.replace({ query: { ...route.query, clause_id: clause.clause_id } }); void recordPosition() }
function target():LibraryTarget | null {return detail.value ? {source_kind:isAsset.value?'asset':'regulation',target_id:detail.value.file_id,asset_version_id:detail.value.asset_version_id} : null}
async function toggleFavorite(){const value=target(),id=request;if(!value || !personalReady.value || savingFavorite.value)return;savingFavorite.value=true;try{const result=await personalApi.saveFavorite(value,!saved.value);if(id!==request)return;saved.value=result.saved;ElMessage.success(result.saved?'已加入我的收藏':'已取消收藏')}catch(e){if(id===request)ElMessage.error(errorText(e,'收藏保存失败'))}finally{if(id===request)savingFavorite.value=false}}
let positionRequest=0
async function recordPosition(){const value=target(),id=request,position=++positionRequest;if(!value || !canSave.value)return;try{await personalApi.rememberReading(value,selected.value?.clause_id);if(id===request && position===positionRequest)readingError.value=''}catch(e){if(id===request && position===positionRequest)readingError.value=errorText(e,'阅读位置未保存，稍后可重试。')}}
let personalRequest=0
async function loadPersonal(id:number){
  const value=target(),personal=++personalRequest
  if(!value || !canSave.value)return
  personalReady.value=false;personalError.value=''
  try{
    const state=await personalApi.state(value)
    if(id!==request || personal!==personalRequest)return
    saved.value=state.saved
    const resume=state.reading?.resume_clause_id
    if(!route.query.clause_id && !selectedId.value && resume){
      let clause=clauses.value.find(c=>c.clause_id===resume)
      if(!clause && isAsset.value){
        try{const found=await clauseApi.clauseDetail(resume);if(id!==request || personal!==personalRequest)return;if(found.file_id===value.target_id && found.asset_version_id===value.asset_version_id){clauses.value.unshift(found);clause=found}}
        catch{/* Unavailable positions never prevent document reading. */}
      }
      if(id!==request || personal!==personalRequest)return
      if(clause && !selectedId.value){selectedId.value=resume;resumed.value=true}
    }
    personalReady.value=true;void recordPosition()
  }catch(e){if(id===request && personal===personalRequest)personalError.value=errorText(e,'收藏和阅读记录读取失败，正文仍可阅读。')}
}
function consult() { router.push({ path: '/qa', query: { q: `关于《${detail.value?.title}》：`, file_id: detail.value?.file_id } }) }
function saveBlob(blob: Blob, name: string) { const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
async function downloadOriginal() { if (!detail.value) return; downloading.value = true; try { saveBlob(await regApi.downloadRegulation(detail.value.file_id), documents.value.find(d => d.doc_type === 'main')?.filename || detail.value.title) } catch (e) { ElMessage.error(errorText(e, '原件下载失败，请联系知识管理员。')) } finally { downloading.value = false } }
async function downloadAttachment(doc: NonNullable<RegulationRow['documents']>[number]) { if (!detail.value) return; downloadingId.value = doc.doc_id; try { saveBlob(isAsset.value && detail.value.asset_version_id ? await regApi.downloadAssetDocument(detail.value.asset_version_id, doc.doc_id) : await regApi.downloadDocument(detail.value.file_id, doc.doc_id), doc.filename || doc.title) } catch (e) { ElMessage.error(errorText(e, '文件下载失败，请联系知识管理员。')) } finally { downloadingId.value = '' } }
let request = 0
let readingRequest = 0, queryTimer: ReturnType<typeof setTimeout> | undefined
async function loadAssetText(reset: boolean) {
  const version = detail.value?.asset_version_id
  if (!version) return
  const id = ++readingRequest; readerLoading.value = true; readerError.value = ''
  try {
    const value = await regApi.assetReading(version, {offset: reset ? 0 : readerOffset.value, limit:200, keyword:contentQuery.value.trim()})
    if (id !== readingRequest || detail.value?.asset_version_id !== version) return
    const merged = reset ? value.clauses : [...clauses.value, ...value.clauses]
    clauses.value = [...new Map(merged.map(clause => [clause.clause_id, clause])).values()]; readerTotal.value = value.total
    readerOffset.value = (reset ? 0 : readerOffset.value) + value.clauses.length
    if (!reset) indexLimit.value += 200
  } catch(e) { if(id===readingRequest) readerError.value = errorText(e, '正文读取失败') }
  finally { if(id===readingRequest) readerLoading.value = false }
}
async function load() {
  ++readingRequest; if(queryTimer) clearTimeout(queryTimer)
  ++positionRequest;++personalRequest;saved.value=false;personalReady.value=false;savingFavorite.value=false;personalError.value='';readingError.value='';resumed.value=false
  const id = ++request; loading.value = true; error.value = ''; detail.value = null; clauses.value = []; chapter.value = ''; contentQuery.value = ''; indexLimit.value = 40
  try {
    if (isAsset.value) {
      const source = await assetApi.detail(route.params.id as string)
      const version = source.versions.find(v => v.version_id === route.query.version && v.release_state==='current' && v.ingestion_state==='ready') || source.versions.find(v=>v.release_state==='current' && v.ingestion_state==='ready')
      if (!version) throw new Error('该资料暂无当前可阅读的发布版本')
      const text = await regApi.assetReading(version.version_id, {limit:200})
      if(id!==request) return
      detail.value={source_kind:'asset',asset_version_id:version.version_id,file_id:source.asset_id,title:source.title,source:version.issuer || '已发布资料',version:version.version_label,status:version.release_state,regulation_code:version.issue_no,secret_level:source.secret_level,domain:version.domain || source.domain,owner_org:version.owner_org || source.owner_org,org_path:'/',effective_date:version.effective_date || null,expiry_date:version.expiry_date,authority_verified:version.authority_verified===true,source_verification:version.source_verification,authority_gaps:version.authority_gaps || [],tags:[source.domain],has_original:false,document_count:version.documents.length,review_note:version.review_note,reviewed_at:version.reviewed_at,documents:version.documents.map(d=>({doc_id:d.document_id,doc_type:d.role,title:d.title,filename:d.filename,mime:'application/octet-stream'}))}
      clauses.value=text.clauses;readerTotal.value=text.total;readerOffset.value=text.clauses.length
      if(typeof route.query.clause_id==='string' && !clauses.value.some(c=>c.clause_id===route.query.clause_id)) {
        const selectedSource=await clauseApi.clauseDetail(route.query.clause_id)
        if(id===request && selectedSource.file_id===source.asset_id && selectedSource.asset_version_id===version.version_id) clauses.value.unshift(selectedSource)
      }
    } else {
      const values = await Promise.all([regApi.regulationDetail(route.params.id as string), regApi.listClauses(route.params.id as string)])
      if(id!==request) return
      detail.value=values[0];clauses.value=values[1]
    }
    if(id===request) {selectedId.value=typeof route.query.clause_id==='string' ? route.query.clause_id : '';void loadPersonal(id)}
  }
  catch (e) { if (id === request) error.value = errorText(e, '该制度不存在、暂不可读取，或不在当前账号权限范围内。') }
  finally { if (id === request) loading.value = false }
}
watch([() => route.params.id, () => route.query.source, () => route.query.version], load, { immediate: true })
watch([contentQuery, chapter], () => { indexLimit.value = 40 })
watch(contentQuery, () => { if(queryTimer) clearTimeout(queryTimer); if(isAsset.value && detail.value) queryTimer=setTimeout(()=>void loadAssetText(true),250) })
onBeforeUnmount(()=>{++request;++readingRequest;++positionRequest;if(queryTimer) clearTimeout(queryTimer)})
</script>

<style scoped>
.back-link { display: inline-block; margin-bottom: 12px; font-size: 12px; text-decoration: none; }.source-note { margin-bottom: 18px; }.source-note a { margin-left: 10px; }.document-workspace { padding: 0 16px 16px; }.document-workspace :deep(.el-tabs__header) { padding-top: 8px; }.reading-toolbar { display: flex; align-items: center; gap: 12px; margin: 14px 0; }.reading-toolbar .el-input { max-width: 460px; }.reading-toolbar > span { color: var(--zg-text-secondary); font-size: 12px; white-space: nowrap; }.reader-layout { display: grid; grid-template-columns: 220px minmax(0, 1fr); border-top: 1px solid var(--zg-border); }.content-index { padding: 12px 12px 0 0; border-right: 1px solid var(--zg-border); }.content-index .el-select { width: 100%; }.index-list { max-height: 62vh; overflow: auto; margin-top: 10px; }.index-list button { display: block; width: 100%; padding: 12px 10px; border: 0; border-bottom: 1px solid var(--zg-border-light); background: #fff; text-align: left; cursor: pointer; }.index-list button.active { background: var(--zg-primary-soft); border-left: 2px solid var(--zg-primary); }.index-list strong { font-size: 12px; color: var(--zg-text); }.index-list small { display: block; margin-top: 6px; color: var(--zg-text-secondary); font-size: 11px; line-height: 1.65; }.index-empty { padding: 14px 10px; color: var(--zg-text-secondary); font-size: 12px; }.reading-article { min-width: 0; }.chapter-label { color: var(--zg-text-secondary); font-size: 12px; }.locator { display: block; margin-top: 7px; color: var(--zg-text-secondary); font-size: 11px; line-height: 1.7; }.reading-footer { display: flex; flex-wrap: wrap; gap: 12px; padding: 16px 22px; border-top: 1px solid var(--zg-border-light); color: var(--zg-text-secondary); font-size: 12px; }.files-note, .sidebar-note { color: var(--zg-text-secondary); font-size: 12px; line-height: 1.8; }.source-details { padding: 0 12px 14px; grid-template-columns: 1fr 1fr; column-gap: 24px; }.related-version { padding: 14px; color: var(--zg-text-secondary); font-size: 12px; }.verified { color: #397553; }.pending { color: #946713; }.source-sidebar .meta-list > div:first-child { padding-top: 0; }
@media (max-width: 1200px) { .detail-layout { grid-template-columns: minmax(0, 1fr); }.source-sidebar .meta-list { grid-template-columns: repeat(3, 1fr); gap: 8px 18px; }.source-sidebar .meta-list > div:first-child { padding-top: 12px; } }
@media (max-width: 760px) { .reader-layout { grid-template-columns: 1fr; }.content-index { padding: 12px 0; border-right: 0; border-bottom: 1px solid var(--zg-border); }.index-list { max-height: 190px; }.source-sidebar .meta-list, .source-details { grid-template-columns: 1fr 1fr; }.document-workspace { padding-inline: 10px; } }
.reading-notice,.source-summary{font-size:12px;line-height:1.8;padding:8px 12px}.reading-notice{color:var(--zg-text-secondary)}.source-summary{margin:14px 0}.reading-toolbar,.source-details{min-width:0}@media(max-width:500px){.reading-toolbar{flex-wrap:wrap}.reading-toolbar .el-input{min-width:0;flex-basis:100%}.source-sidebar .meta-list,.source-details{grid-template-columns:minmax(0,1fr)}}
</style>
