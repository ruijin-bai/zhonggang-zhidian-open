<template>
  <section class="personal-library" v-loading="loading">
    <div class="toolbar"><el-input v-model="keyword" clearable :maxlength="200" :placeholder="view === 'favorites' ? '搜索收藏的制度或咨询' : '搜索阅读过的制度'" aria-label="搜索个人资料"/><span class="count">{{ loaded ? total+' 份制度' : loading ? '正在读取' : '未读取' }}</span></div>
    <DataState :error="error" :empty="loaded && !rows.length" :empty-title="keyword ? '没有匹配的制度' : view === 'favorites' ? '还没有收藏制度' : '还没有阅读记录'" :empty-description="view === 'favorites' ? '在制度详情中加入收藏，常用资料就能从这里直接打开。' : '打开制度并阅读后，会记住本人的阅读位置。'" @retry="load"><template #actions><el-button v-if="keyword" @click="keyword=''">清除关键词</el-button><router-link v-else to="/library">查找制度</router-link></template>
      <el-table class="desktop-documents" :data="rows" border @row-click="open"><el-table-column label="制度 / 文号" min-width="290"><template #default="{row}"><button class="table-link" @click.stop="open(row)">{{ row.title }}</button><div class="row-note">{{ row.regulation_code || '未记录文号' }}</div></template></el-table-column><el-table-column label="现行版本" width="110"><template #default="{row}">{{ row.version }}</template></el-table-column><el-table-column label="阅读位置" min-width="250"><template #default="{row}"><span>{{ positionLabel(row) }}</span><div class="row-note">{{ row.read_at ? `上次阅读 ${time(row.read_at)}` : `收藏于 ${time(row.recorded_at)}` }}</div></template></el-table-column><el-table-column v-if="view==='favorites'" label="管理" width="105"><template #default="{row}"><el-button text :disabled="!!saving" :loading="saving===key(row)" @click.stop="removeDocument(row)">取消收藏</el-button></template></el-table-column></el-table>
      <ul class="mobile-documents"><li v-for="row in rows" :key="key(row)"><button class="table-link" @click="open(row)">{{ row.title }}</button><div class="row-note">{{ row.version }} · {{ row.regulation_code || '未记录文号' }}</div><div class="row-note">{{ positionLabel(row) }} · {{ time(row.read_at || row.recorded_at) }}</div><el-button v-if="view==='favorites'" text :disabled="!!saving" :loading="saving===key(row)" @click="removeDocument(row)">取消收藏</el-button></li></ul>
      <div class="pagination-bar"><span>仅列当前有效且仍有权查看的资料。</span><el-pagination v-model:current-page="page" :page-size="15" :total="total" layout="prev, pager, next"/></div>
    </DataState>
    <p class="personal-note">记录保存于本人账号。取消收藏不会删除制度；阅读位置不代表已办理或已审批。</p>
    <section v-if="view==='favorites'" class="work-panel saved-answers"><div class="panel-head">收藏的咨询 <small>{{ answersLoaded ? answerTotal+' 条' : '未读取' }}</small></div><div class="panel-body"><DataState :error="answerError" :empty="answersLoaded && !answers.length" empty-title="暂无收藏的咨询" empty-description="在咨询结果中点击收藏后，可从这里继续查看；只列本人已保存回答且引用来源仍可读的记录。" @retry="load"><ul class="answer-list"><li v-for="answer in answers" :key="answer.session_id"><div><router-link :to="{path:'/qa',query:{session:answer.session_id}}">{{ answer.question }}</router-link><p>{{ answer.answer_excerpt }}</p><small>{{ time(answer.saved_at) }}</small></div><el-button text :disabled="!!saving" :loading="saving===answer.session_id" @click="removeAnswer(answer)">取消收藏</el-button></li></ul><el-pagination v-model:current-page="answerPage" :page-size="15" :total="answerTotal" layout="prev, pager, next"/></DataState></div></section>
  </section>
</template>
<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {ElMessage} from 'element-plus'
import * as api from '@/api/personalLibrary'
import type {PersonalDocument,SavedAnswer} from '@/api/personalLibrary'
import DataState from '@/components/DataState.vue'
import {errorText} from '@/utils/presentation'
const props=defineProps<{view:string}>(),route=useRoute(),router=useRouter()
const loading=ref(false),loaded=ref(false),error=ref(''),answerError=ref(''),answersLoaded=ref(false),saving=ref(''),keyword=ref(''),page=ref(1),answerPage=ref(1)
const rows=ref<PersonalDocument[]>([]),total=ref(0),answers=ref<SavedAnswer[]>([]),answerTotal=ref(0)
let request=0,applyingQuery=false,timer:ReturnType<typeof setTimeout>|undefined
const parsePage=(value:unknown)=>typeof value==='string' && /^[1-9]\d*$/.test(value) ? Math.min(Number(value),100000) : 1
function syncQuery(){if(applyingQuery || route.path!=='/library')return;void router.replace({query:{...route.query,personal_q:keyword.value || undefined,personal_page:page.value>1?String(page.value):undefined,answer_page:answerPage.value>1?String(answerPage.value):undefined}})}
watch(keyword,()=>{if(applyingQuery)return;loading.value=true;loaded.value=false;answersLoaded.value=false;error.value='';answerError.value='';applyingQuery=true;page.value=1;answerPage.value=1;applyingQuery=false;if(timer)clearTimeout(timer);timer=setTimeout(syncQuery,250)},{flush:'sync'})
watch([page,answerPage],syncQuery,{flush:'sync'})
watch(()=>[props.view,route.query.personal_q,route.query.personal_page,route.query.answer_page],()=>{applyingQuery=true;keyword.value=typeof route.query.personal_q==='string'?route.query.personal_q:'';page.value=parsePage(route.query.personal_page);answerPage.value=parsePage(route.query.answer_page);applyingQuery=false;void load()},{immediate:true})
function time(value:string){const utc=/Z$|[+-]\d{2}:\d{2}$/.test(value)?value:value+'Z';return new Date(utc).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
function key(row:PersonalDocument){return row.source_kind+':'+row.target_id}
function positionLabel(row:PersonalDocument){return row.version_changed ? '版本已更新，请核对现行资料' : row.resume_clause_id ? '打开后继续上次阅读' : '从正文开始阅读'}
function open(row:PersonalDocument){if(timer)clearTimeout(timer);const from=router.resolve({path:'/library',query:{...route.query,personal_q:keyword.value || undefined}}).fullPath;void router.push({path:'/library/'+encodeURIComponent(row.target_id),query:{from,...(row.source_kind==='asset'?{source:'asset',version:row.asset_version_id || undefined}:{}),clause_id:row.resume_clause_id || undefined}})}
async function load(){
  const id=++request,view=props.view;loading.value=true;error.value='';answerError.value=''
  const results=await Promise.allSettled([view==='recent'?api.recent((page.value-1)*15,15,keyword.value):api.favorites((page.value-1)*15,15,keyword.value),view==='favorites'?api.answerFavorites((answerPage.value-1)*15,15,keyword.value):Promise.resolve(null)])
  if(id!==request || view!==props.view)return
  const documents=results[0]
  if(documents.status==='fulfilled' && documents.value){const value=documents.value as api.PersonalPage<PersonalDocument>;rows.value=value.items;total.value=value.total;loaded.value=true;if(page.value>Math.max(1,Math.ceil(total.value/15)))page.value=Math.max(1,Math.ceil(total.value/15))}
  else if(documents.status==='rejected'){error.value=errorText(documents.reason,'个人资料读取失败');loaded.value=false}
  const saved=results[1]
  if(view==='favorites'){if(saved.status==='fulfilled' && saved.value){const value=saved.value as api.PersonalPage<SavedAnswer>;answers.value=value.items;answerTotal.value=value.total;answersLoaded.value=true;if(answerPage.value>Math.max(1,Math.ceil(answerTotal.value/15)))answerPage.value=Math.max(1,Math.ceil(answerTotal.value/15))}else if(saved.status==='rejected'){answerError.value=errorText(saved.reason,'收藏咨询读取失败');answersLoaded.value=false}}
  if(id===request)loading.value=false
}
async function removeDocument(row:PersonalDocument){if(saving.value)return;saving.value=key(row);try{await api.saveFavorite({source_kind:row.source_kind,target_id:row.target_id,asset_version_id:row.asset_version_id},false);rows.value=rows.value.filter(item=>key(item)!==key(row));total.value=Math.max(0,total.value-1);ElMessage.success('已取消收藏');await load()}catch(e){ElMessage.error(errorText(e,'取消收藏失败'))}finally{saving.value=''}}
async function removeAnswer(row:SavedAnswer){if(saving.value)return;saving.value=row.session_id;try{await api.removeAnswerFavorite(row.session_id);answers.value=answers.value.filter(item=>item.session_id!==row.session_id);answerTotal.value=Math.max(0,answerTotal.value-1);ElMessage.success('已取消收藏');await load()}catch(e){ElMessage.error(errorText(e,'取消收藏失败'))}finally{saving.value=''}}
defineExpose({refresh:load})
onBeforeUnmount(()=>{++request;if(timer)clearTimeout(timer)})
</script>
<style scoped>
.personal-library{min-width:0}.toolbar .el-input{max-width:460px}.count,.row-note,.personal-note{color:var(--zg-text-secondary);font-size:12px;line-height:1.7}.row-note{margin-top:5px}.saved-answers{margin-top:24px;min-width:0}.answer-list{list-style:none;padding:0;margin:0}.answer-list li{display:flex;align-items:start;justify-content:space-between;gap:20px;padding:14px 0;border-bottom:1px solid var(--zg-border-light)}.answer-list li>div{min-width:0;overflow-wrap:anywhere}.answer-list li>.el-button{flex-shrink:0}.answer-list p,.answer-list small{color:var(--zg-text-secondary);font-size:12px;line-height:1.7}.answer-list p{margin:8px 0}.saved-answers :deep(.el-pagination){margin-top:16px}@media(max-width:600px){.answer-list li{flex-wrap:wrap}}
.mobile-documents{display:none;list-style:none;margin:0;padding:0}.mobile-documents li{padding:14px;background:#fff;border-bottom:1px solid var(--zg-border-light);overflow-wrap:anywhere}.mobile-documents .table-link{text-align:left;line-height:1.7}.mobile-documents .el-button{margin:8px 0 0;padding:0}@media(max-width:600px){.desktop-documents{display:none}.mobile-documents{display:block}}
</style>
