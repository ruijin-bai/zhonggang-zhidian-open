<template>
  <div class="zg-container review-page">
    <PageHeader title="审核中心" description="集中核对制度与资料原文、办理规则、事项结论及员工纠错。"><template #actions><el-button :loading="loading" @click="load">刷新待办</el-button></template></PageHeader>
    <div class="review-overview"><button v-for="item in taskKinds" :key="item.key" type="button" :class="{active:tab===item.key}" @click="selectTab(item.key)"><span>{{ item.label }}</span><strong>{{ item.count===null ? '—' : item.count }}</strong><small>{{ item.note }}</small></button></div>
    <section class="work-panel" v-loading="loading">
      <div class="panel-head"><span>{{ currentKind.label }}</span><small>{{ currentKind.note }}</small></div>
      <div v-if="tab==='feedback'" class="toolbar"><el-select v-model="feedbackStatus" style="width:140px"><el-option label="待处理" value="pending" /><el-option label="已处理" value="resolved" /><el-option label="全部记录" value="all" /></el-select><span class="muted">{{ visibleFeedbacks.length }} 条反馈</span></div>
      <DataState :error="errors[tab]" :empty="!loading && (tab==='feedback' ? !visibleFeedbacks.length : currentKind.count===0)" empty-title="当前没有此类待办" empty-description="新任务进入后会显示在这里，也可以查看其他审核类型。" @retry="load">
        <template v-if="tab==='regulation'">
          <el-table :data="rows" size="small" class="clickable-table" @row-click="openPreview"><el-table-column prop="title" label="制度名称" min-width="260" show-overflow-tooltip /><el-table-column prop="regulation_code" label="制度编码" width="170" show-overflow-tooltip /><el-table-column prop="version" label="版本" width="85" /><el-table-column label="生效日期" width="120"><template #default="{row}">{{ row.effective_date || '待核验' }}</template></el-table-column><el-table-column label="密级" width="90"><template #default="{row}">{{ secretLabel(row.secret_level) }}</template></el-table-column><el-table-column label="操作" width="100"><template #default="{row}"><el-button text type="primary" @click.stop="openPreview(row)">查看并审核</el-button></template></el-table-column></el-table>
        </template>
        <template v-else-if="tab==='rule'">
          <el-table :data="ruleRows" size="small"><el-table-column prop="rule_key" label="规则名称 / 编号" min-width="240" show-overflow-tooltip /><el-table-column label="事项类型" width="120"><template #default="{row}">{{ scenarioLabel(row.scenario) }}</template></el-table-column><el-table-column prop="file_title" label="依据制度" min-width="260" show-overflow-tooltip /><el-table-column prop="clause_no" label="条款" width="100" /><el-table-column label="操作" width="130"><template #default="{row}"><el-button text type="primary" @click="router.push({path:'/rules',query:{tab:'pending',id:row.rule_id}})">核对原文并审核</el-button></template></el-table-column></el-table>
        </template>
        <template v-else-if="tab==='case'">
          <el-table :data="caseRows" size="small"><el-table-column prop="title" label="事项名称" min-width="230" show-overflow-tooltip /><el-table-column prop="case_no" label="事项编号" width="180" /><el-table-column prop="decision_summary" label="需复核原因" min-width="280" show-overflow-tooltip /><el-table-column label="操作" width="130"><template #default="{row}"><el-button text type="primary" @click="router.push({path:'/case',query:{tab:'queue',id:row.case_id}})">查看事实并复核</el-button></template></el-table-column></el-table>
        </template>
        <template v-else-if="tab==='asset'">
          <el-table :data="assetRows" size="small" class="clickable-table" @row-click="openAssetReview"><el-table-column prop="title" label="资料名称" min-width="260" show-overflow-tooltip /><el-table-column prop="issue_no" label="正式文号" min-width="170" show-overflow-tooltip /><el-table-column prop="version_label" label="版本" width="100" /><el-table-column prop="effective_date" label="生效日期" width="125" /><el-table-column label="操作" width="125"><template #default="{row}"><el-button text type="primary" @click.stop="openAssetReview(row)">核对原文并审核</el-button></template></el-table-column></el-table>
        </template>
        <template v-else>
          <el-table :data="visibleFeedbacks" size="small" class="clickable-table" @row-click="openFeedback"><el-table-column prop="question" label="原问题" min-width="260" show-overflow-tooltip /><el-table-column prop="content" label="员工指出的问题" min-width="260" show-overflow-tooltip /><el-table-column label="提交时间" width="165"><template #default="{row}">{{ formatDate(row.created_at) }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="{row}"><el-tag :type="row.resolved ? 'success' : 'warning'" effect="plain">{{ row.resolved ? '已处理' : '待处理' }}</el-tag></template></el-table-column><el-table-column label="操作" width="110"><template #default="{row}"><el-button text type="primary" @click.stop="openFeedback(row)">{{ row.resolved ? '查看处理记录' : '核对并处理' }}</el-button></template></el-table-column></el-table>
        </template>
      </DataState>
    </section>

    <el-drawer v-model="previewVisible" :title="preview.title || '制度发布审核'" size="min(960px, 96vw)" v-loading="previewLoading">
      <DataState v-if="previewError" :error="previewError" @retry="openPreview(activeRow)" />
      <template v-else-if="preview.file_id || preview.title">
        <div class="review-purpose">发布前核对制度身份、适用范围及条款质量。审核通过后员工可检索，系统按权限生成更新通知。</div>
        <el-descriptions :column="2" border size="small"><el-descriptions-item label="制度编码">{{ preview.regulation_code || '待核验' }}</el-descriptions-item><el-descriptions-item label="版本">{{ preview.version }}</el-descriptions-item><el-descriptions-item label="来源">{{ preview.source || '待核验' }}</el-descriptions-item><el-descriptions-item label="生效日期">{{ preview.effective_date || '待核验' }}</el-descriptions-item><el-descriptions-item label="密级">{{ secretLabel(preview.secret_level || activeRow?.secret_level) }}</el-descriptions-item><el-descriptions-item label="替代版本">{{ preview.replaces_file_id ? '本次为替代版本，请核对新旧口径' : '无替代记录' }}</el-descriptions-item></el-descriptions>
        <section class="review-content"><h3>待发布条款（{{ preview.clauses?.length || 0 }}）</h3><div v-if="!preview.clauses?.length" class="inline-warning">未返回条款，请先核对解析结果。</div><article v-for="clause in preview.clauses || []" :key="clause.clause_id || clause.clause_no" class="clause-reading"><div class="clause-heading"><strong>{{ clause.clause_no }}</strong><span>{{ (clause.scenario_tags || []).join('、') }}</span></div><p>{{ clause.content }}</p></article></section>
        <section class="review-input"><h3>审核决定</h3><el-checkbox v-model="checked">已核对制度来源、生效日期、替代关系及条款原文。</el-checkbox><el-input v-model="reviewNote" type="textarea" :rows="3" placeholder="填写审核意见；退回时请给出明确的补充或修正要求。" /><p v-if="decisionError" class="inline-error" role="alert">{{ decisionError }}</p></section>
      </template>
      <template #footer><el-button @click="previewVisible=false">关闭</el-button><el-button :loading="deciding" :disabled="previewLoading || !!previewError" @click="decide(false)">退回修正</el-button><el-button type="primary" :loading="deciding" :disabled="!checked || previewLoading || !!previewError || !preview.clauses?.length" @click="decide(true)">通过并发布</el-button></template>
    </el-drawer>

    <el-drawer v-model="assetReviewVisible" :title="assetDetail?.title || '资料发布审核'" size="min(1080px, 96vw)">
      <div v-loading="assetReviewLoading"><DataState :error="assetReviewError" @retry="openAssetReview(selectedAsset)"><template v-if="assetDetail && reviewAssetVersion">
        <div class="review-purpose">核对来源信息和各文件的正文定位。必备文件存在处理问题或正文无可引用内容时，系统阻止发布。</div>
        <el-descriptions :column="2" border size="small"><el-descriptions-item label="正式文号">{{ reviewAssetVersion.issue_no || '待核对' }}</el-descriptions-item><el-descriptions-item label="版本">{{ reviewAssetVersion.version_label }}</el-descriptions-item><el-descriptions-item label="生效日期">{{ reviewAssetVersion.effective_date || '待核对' }}</el-descriptions-item><el-descriptions-item label="失效日期">{{ reviewAssetVersion.expiry_date || '未设置' }}</el-descriptions-item><el-descriptions-item label="责任部门">{{ reviewAssetVersion.owner_org_name || '待核对' }}</el-descriptions-item><el-descriptions-item label="业务领域">{{ reviewAssetVersion.domain || assetDetail.domain }}</el-descriptions-item></el-descriptions>
        <p v-if="reviewAssetVersion.publication_gate?.errors.length" class="inline-warning">{{ reviewAssetVersion.publication_gate.errors.join('；') }}</p>
        <section class="review-content"><h3>文件与原文</h3><el-table :data="reviewAssetVersion.documents" size="small" border><el-table-column prop="filename" label="文件" min-width="250" /><el-table-column label="文件用途" width="145"><template #default="{row}">{{ assetRoleLabel(row.role) }}<small class="document-note">{{ row.normative ? '规范依据' : row.mandatory ? '必备材料' : '辅助材料' }}</small></template></el-table-column><el-table-column label="内容状态" width="110"><template #default="{row}">{{ assetParseLabel(row.parse_status) }}</template></el-table-column><el-table-column label="原文" width="95"><template #default="{row}"><el-button text type="primary" :disabled="!row.parse_run_id" @click="readAssetDocument(row.document_id)">核对内容</el-button></template></el-table-column></el-table>
          <div v-if="reviewDocumentId" class="asset-review-reader" v-loading="assetContentLoading"><DataState :error="assetContentError" :empty="!assetContentLoading && !assetTree.nodes.length" empty-title="没有可阅读的原文内容" @retry="loadAssetContent(assetContentPage)"><p class="muted">{{ assetTree.filename }} · 原文定位随正文显示</p><article v-for="node in assetReadableNodes" :key="node.node_id" class="clause-reading"><strong v-if="node.title || node.label">{{ [node.label,node.title].filter(Boolean).join(' ') }}</strong><div v-if="node.structure.values?.length" class="asset-row-values"><span v-for="(value,index) in node.structure.values" :key="index">{{ value || '—' }}</span></div><p v-else>{{ node.text }}</p><small class="muted">{{ node.source_locator || (node.source_page ? `第 ${node.source_page} 页` : '缺少原文定位') }}</small></article><el-pagination v-if="assetTree.total>100" layout="total, prev, pager, next" :current-page="assetContentPage" :page-size="100" :total="assetTree.total" @current-change="loadAssetContent" /></DataState></div>
        </section><section class="review-input"><h3>资料审核决定</h3><el-checkbox v-model="assetChecked">已逐项核对正式来源、文件用途、必备文件和可引用原文。</el-checkbox><el-input v-model="assetReviewNote" type="textarea" :rows="3" placeholder="填写核验依据及审核意见；退回时说明需要补充或修正的内容。" /><p v-if="assetDecisionError" class="inline-error" role="alert">{{ assetDecisionError }}</p></section>
      </template></DataState></div><template #footer><el-button @click="assetReviewVisible=false">关闭</el-button><el-button :loading="assetDeciding" :disabled="assetReviewLoading || !!assetReviewError || !reviewAssetVersion" @click="decideAsset(false)">退回修正</el-button><el-button type="primary" :loading="assetDeciding" :disabled="!assetChecked || !assetReviewNote.trim() || assetReviewLoading || !!assetReviewError || !reviewAssetVersion?.publication_gate?.publishable" @click="decideAsset(true)">通过并发布资料</el-button></template>
    </el-drawer>

    <el-drawer v-model="feedbackVisible" title="员工纠错处理" size="min(760px, 95vw)">
      <template v-if="selectedFeedback"><el-tag :type="selectedFeedback.resolved ? 'success' : 'warning'" effect="plain">{{ selectedFeedback.resolved ? '已处理' : '待处理' }}</el-tag><section class="feedback-section"><h3>原问题</h3><p>{{ selectedFeedback.question }}</p></section><section class="feedback-section"><h3>员工指出的问题</h3><p>{{ selectedFeedback.content || '员工未填写具体说明，请结合原问题进一步核对。' }}</p></section><section class="feedback-section"><h3>待核对的答案摘录</h3><p>{{ selectedFeedback.answer_excerpt || '当前反馈未返回答案摘录' }}</p><el-button plain @click="router.push('/library')">查阅相关制度</el-button></section><section class="feedback-section"><h3>{{ selectedFeedback.resolved ? '处理记录' : '处理意见' }}</h3><template v-if="selectedFeedback.resolved"><p>{{ selectedFeedback.resolved_note || '已记录处理完成' }}</p><small class="muted">{{ formatDate(selectedFeedback.resolved_at) }}</small></template><template v-else><el-input v-model="feedbackNote" type="textarea" :rows="5" placeholder="记录核对依据、问题判断、采取的实际修正和反馈意见。需要修改制度或规则时，请完成对应维护后再记录结果。" /><p class="muted">本操作保存处理意见与完成状态；制度与规则的修正记录由对应维护流程保存。</p><p v-if="feedbackError" class="inline-error" role="alert">{{ feedbackError }}</p></template></section></template>
      <template #footer><el-button @click="feedbackVisible=false">关闭</el-button><el-button v-if="selectedFeedback && !selectedFeedback.resolved" type="primary" :loading="feedbackSaving" :disabled="!feedbackNote.trim()" @click="resolveFeedback">保存处理意见并完成</el-button></template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as regApi from '@/api/regulation'
import * as ruleApi from '@/api/rule'
import * as caseApi from '@/api/businessCase'
import * as assetApi from '@/api/asset'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
const route=useRoute();const router=useRouter();const loading=ref(false);const tab=ref('regulation');const rows=ref<any[]>([]);const ruleRows=ref<ruleApi.DecisionRuleOut[]>([]);const caseRows=ref<caseApi.BusinessCaseOut[]>([]);const feedbacks=ref<any[]>([]);const errors=ref<Record<string,string>>({});const loaded=ref<Record<string,boolean>>({})
const previewVisible=ref(false);const previewLoading=ref(false);const previewError=ref('');const preview=ref<any>({});const activeRow=ref<any>(null);const checked=ref(false);const reviewNote=ref('');const decisionError=ref('');const deciding=ref(false);let previewVersion=0
const feedbackVisible=ref(false);const feedbackStatus=ref('pending');const selectedFeedback=ref<any>(null);const feedbackNote=ref('');const feedbackError=ref('');const feedbackSaving=ref(false)
const assetRows=ref<assetApi.PendingAssetReview[]>([]);const assetReviewVisible=ref(false);const assetReviewLoading=ref(false);const assetReviewError=ref('');const selectedAsset=ref<assetApi.PendingAssetReview|null>(null);const assetDetail=ref<assetApi.AssetDetail|null>(null);const assetChecked=ref(false);const assetReviewNote=ref('');const assetDecisionError=ref('');const assetDeciding=ref(false)
const reviewAssetVersion=computed(()=>assetDetail.value?.versions.find(version=>version.version_id===selectedAsset.value?.version_id));const reviewDocumentId=ref('');const assetContentLoading=ref(false);const assetContentError=ref('');const assetContentPage=ref(1);const assetTree=ref<assetApi.DocumentTree>({document_id:'',filename:'',total:0,offset:0,limit:100,nodes:[]});const assetReadableNodes=computed(()=>assetTree.value.nodes.filter(node=>node.node_type!=='table_cell' && node.node_type!=='document' && (node.text || node.title || node.label)))
let assetPreviewRequest=0;let assetContentRequest=0
const visibleFeedbacks=computed(()=>feedbacks.value.filter(row=>feedbackStatus.value==='all' || (feedbackStatus.value==='resolved' ? row.resolved : !row.resolved)))
const taskKinds=computed(()=>[
  {key:'regulation',label:'制度发布',count:loaded.value.regulation ? rows.value.length : null,note:'核验原文后发布'},
  {key:'asset',label:'资料发布',count:loaded.value.asset ? assetRows.value.length : null,note:'核对正文、附件与来源'},
  {key:'rule',label:'办理规则',count:loaded.value.rule ? ruleRows.value.length : null,note:'核对条件与审批口径'},
  {key:'case',label:'事项复核',count:loaded.value.case ? caseRows.value.length : null,note:'确认事实与办理指南'},
  {key:'feedback',label:'员工纠错',count:loaded.value.feedback ? feedbacks.value.filter(row=>!row.resolved).length : null,note:'核实问题并记录处理'},
])
const currentKind=computed(()=>taskKinds.value.find(item=>item.key===tab.value) || taskKinds.value[0])
function formatDate(value?:string){return value ? value.slice(0,19).replace('T',' ') : '—'}
function secretLabel(value?:string){return ({public:'公开',internal:'内部',confidential:'机密',secret:'绝密'} as Record<string,string>)[value || ''] || value || '待核验'}
function scenarioLabel(value:string){return ({contract_change:'合同变更',payment:'付款申请',procurement:'采购事项',safety:'安全事项',employment:'用工事项'} as Record<string,string>)[value] || value}
function selectTab(value:string){tab.value=value;router.replace({path:'/review',query:{tab:value}})}
async function load(){
  loading.value=true
  const results=await Promise.allSettled([regApi.listPendingReviews(),ruleApi.pendingRuleReviews(),caseApi.reviewQueue(),regApi.listFeedbacks(),assetApi.pendingReviews()])
  const keys=['regulation','rule','case','feedback','asset'];const targets=[rows,ruleRows,caseRows,feedbacks,assetRows]
  results.forEach((result,index)=>{const key=keys[index];if(result.status==='fulfilled'){targets[index].value=key==='feedback' ? (result.value as any[]).filter(row=>row.type==='correct') : result.value as any;errors.value[key]='';loaded.value[key]=true}else{errors.value[key]=result.reason?.message || '待办加载失败，请重试';loaded.value[key]=false}})
  loading.value=false
}
function assetRoleLabel(role:string){return ({normative_body:'制度正文',normative_annex:'规范附件',standard_table:'标准表格',form:'配套表单',template:'配套模板',flowchart:'流程图',training:'培训材料',reference:'参考资料',raw_asset:'原始素材'} as Record<string,string>)[role] || role}
function assetParseLabel(status:string){return ({succeeded:'处理完成',pending:'待处理',processing:'处理中',failed:'处理失败',requires_ocr:'需文字识别',needs_review:'待核对'} as Record<string,string>)[status] || status}
async function openAssetReview(row:assetApi.PendingAssetReview|null){
  if(!row)return;const request=++assetPreviewRequest;++assetContentRequest;selectedAsset.value=row;assetDetail.value=null;assetReviewVisible.value=true;assetReviewLoading.value=true;assetReviewError.value='';assetChecked.value=false;assetReviewNote.value='';assetDecisionError.value='';reviewDocumentId.value='';assetTree.value={document_id:'',filename:'',total:0,offset:0,limit:100,nodes:[]}
  try{const detail=await assetApi.detail(row.asset_id);if(request!==assetPreviewRequest)return;assetDetail.value=detail;const first=reviewAssetVersion.value?.documents.find(doc=>doc.parse_run_id);if(first)await readAssetDocument(first.document_id)}catch(error:any){if(request===assetPreviewRequest)assetReviewError.value=error?.message || '资料原文加载失败'}finally{if(request===assetPreviewRequest)assetReviewLoading.value=false}
}
async function readAssetDocument(documentId:string){reviewDocumentId.value=documentId;await loadAssetContent(1)}
async function loadAssetContent(page:number){if(!reviewDocumentId.value)return;const request=++assetContentRequest;assetContentLoading.value=true;assetContentError.value='';assetContentPage.value=page;try{const result=await assetApi.tree(reviewDocumentId.value,{offset:(page-1)*100,limit:100});if(request===assetContentRequest)assetTree.value=result}catch(error:any){if(request===assetContentRequest)assetContentError.value=error?.message || '资料内容读取失败'}finally{if(request===assetContentRequest)assetContentLoading.value=false}}
async function decideAsset(approved:boolean){if(!reviewAssetVersion.value || assetDeciding.value)return;if(!assetReviewNote.value.trim()){assetDecisionError.value='请填写核对依据和审核意见';return}if(approved && !assetChecked.value)return;assetDeciding.value=true;assetDecisionError.value='';try{await assetApi.reviewVersion(reviewAssetVersion.value.version_id,{decision:approved ? 'approve' : 'reject',note:assetReviewNote.value.trim()});assetReviewVisible.value=false;await load();ElMessage.success(approved ? '资料已发布，员工可按权限读取' : '资料已退回维护人员修正')}catch(error:any){assetDecisionError.value=error?.message || '资料审核提交失败'}finally{assetDeciding.value=false}}
async function openPreview(row:any){
  if(!row)return
  const version=++previewVersion
  activeRow.value=row;preview.value={};previewVisible.value=true;previewLoading.value=true;previewError.value='';checked.value=false;reviewNote.value='';decisionError.value=''
  try{const result=await regApi.previewPendingReview(row.file_id);if(version===previewVersion)preview.value=result}catch(error:any){if(version===previewVersion)previewError.value=error?.message || '制度原文加载失败'}finally{if(version===previewVersion)previewLoading.value=false}
}
async function decide(approved:boolean){
  if(!activeRow.value || deciding.value)return
  if(approved && !checked.value)return
  if(!approved && !reviewNote.value.trim()){decisionError.value='请填写明确的修正或补充要求';return}
  deciding.value=true;decisionError.value=''
  try{await regApi.reviewRegulation(activeRow.value.file_id,{approved,note:reviewNote.value.trim()});previewVisible.value=false;await load();ElMessage.success(approved ? '制度已发布，员工可按权限检索' : '已退回知识库管理员')}catch(error:any){decisionError.value=error?.message || '审核提交失败'}finally{deciding.value=false}
}
function openFeedback(row:any){selectedFeedback.value=row;feedbackVisible.value=true;feedbackNote.value='';feedbackError.value=''}
async function resolveFeedback(){
  if(!selectedFeedback.value || feedbackSaving.value || !feedbackNote.value.trim())return
  feedbackSaving.value=true;feedbackError.value=''
  try{await regApi.resolveFeedback(selectedFeedback.value.fb_id,feedbackNote.value.trim());await load();selectedFeedback.value=feedbacks.value.find(row=>row.fb_id===selectedFeedback.value.fb_id) || {...selectedFeedback.value,resolved:true,resolved_note:feedbackNote.value};ElMessage.success('处理意见已保存')}catch(error:any){feedbackError.value=error?.message || '处理意见保存失败'}finally{feedbackSaving.value=false}
}
watch(()=>route.query.tab,(value)=>{tab.value=['regulation','asset','rule','case','feedback'].includes(String(value)) ? String(value) : 'regulation'},{immediate:true})
onMounted(async()=>{await load();if(route.query.version){const row=assetRows.value.find(item=>item.version_id===String(route.query.version));if(row)await openAssetReview(row)}})
</script>

<style scoped>
.review-page{display:flex;flex-direction:column;gap:14px}.review-overview{display:grid;grid-template-columns:repeat(4,1fr);border:1px solid var(--zg-border);background:#fff}.review-overview button{display:grid;grid-template-columns:1fr auto;gap:5px;padding:14px 16px;border:0;border-right:1px solid var(--zg-border);background:#fff;text-align:left;color:var(--zg-text);cursor:pointer}.review-overview button:last-child{border-right:0}.review-overview button.active{background:var(--zg-primary-soft);box-shadow:inset 0 -3px var(--zg-primary)}.review-overview strong{grid-row:1/3;grid-column:2;font-size:26px;align-self:center;color:var(--zg-primary)}.review-overview span{font-weight:600}.review-overview small{color:var(--zg-text-secondary);font-size:12px}.panel-head{display:flex;justify-content:space-between;gap:12px}.panel-head small,.muted{color:var(--zg-text-secondary);font-size:12px;font-weight:400;line-height:1.7}.toolbar{display:flex;gap:10px;align-items:center;padding:12px 16px}.clickable-table :deep(tr){cursor:pointer}.review-purpose{padding:12px;margin-bottom:16px;background:var(--zg-primary-soft);color:var(--zg-text-secondary);line-height:1.7}.review-content,.review-input,.feedback-section{margin-top:20px}h3{font-size:14px;margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid var(--zg-border)}.clause-reading{border:1px solid var(--zg-border);padding:12px 16px;margin-bottom:10px}.clause-heading{display:flex;justify-content:space-between;gap:12px}.clause-heading span{color:var(--zg-text-secondary);font-size:12px}.clause-reading p,.feedback-section p{white-space:pre-wrap;line-height:1.85;margin:8px 0}.review-input .el-textarea{margin-top:10px}.inline-error{padding:10px;color:#a33a2b;background:#fff5f2;line-height:1.7}.inline-warning{padding:12px;background:#fffaf0;color:#80500a}@media(max-width:800px){.review-overview{grid-template-columns:1fr 1fr}.review-overview button{border-bottom:1px solid var(--zg-border)}}
.review-overview{grid-template-columns:repeat(5,1fr)}.document-note{display:block;font-size:11px;color:var(--zg-text-secondary);margin-top:5px}.asset-review-reader{margin-top:16px}.asset-row-values{display:flex;border:1px solid var(--zg-border);overflow-x:auto;margin:8px 0}.asset-row-values span{padding:8px;min-width:85px;flex:1;border-right:1px solid var(--zg-border);font-size:12px;line-height:1.7}@media(max-width:800px){.review-overview{grid-template-columns:1fr 1fr}}
</style>
