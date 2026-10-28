<template>
  <div class="zg-container clause-page" v-loading="loading">
    <div class="back-links"><el-button text @click="goBack">‹ 返回上一步</el-button><router-link to="/library">制度目录</router-link></div>
    <PageHeader title="引用原文" :description="detail?.file_title || '核对引用内容与原件位置'" />
    <DataState :error="error" @retry="load">
      <el-alert v-if="detail?.historical" :title="detail.snapshot_only ? '历史引用摘录：无法核对完整原文校验值，以下保留当时引用内容。' : '历史引用原文：用于追溯当时依据，不代表当前仍可办理。'" type="warning" :closable="false" style="margin-bottom:16px" />
      <div v-if="detail" class="detail-layout">
        <article class="work-panel">
          <div class="reading-header"><span class="clause-parent">{{ detail.chapter || detail.document_title || detail.file_title }}</span><h2>{{ detail.clause_no || '正文片段' }}</h2><p class="source-location">{{ sourceLocation(detail.source_locator, detail.source_page) }}</p></div>
          <div class="reading-content"><p class="reading-text">{{ detail.content }}</p></div>
          <div class="reading-footer"><span>以上为资料原文摘录。具体办理要求需结合完整上下文和生效范围。</span></div>
        </article>
        <aside class="work-panel">
          <div class="panel-head">引用来源</div>
          <div class="panel-body"><dl class="meta-list"><div><dt>所属制度</dt><dd>{{ detail.file_title }}</dd></div><div><dt>版本</dt><dd>{{ detail.file_version || '未记录' }}</dd></div><div><dt>发布状态</dt><dd>{{ statusName(detail.file_status) }}</dd></div><div><dt>密级</dt><dd>{{ secretName(detail.secret_level) }}</dd></div><div v-if="detail.tags?.length"><dt>分类与用途</dt><dd>{{ detail.tags.map(tagName).join('、') }}</dd></div></dl>
            <router-link v-if="!detail.historical" class="source-link" :to="{ path: '/library/' + detail.file_id, query: detail.source_kind === 'asset' ? { source:'asset',version:detail.asset_version_id,clause_id:detail.clause_id } : { clause_id:detail.clause_id } }">阅读完整制度 ›</router-link>
            <el-button v-else text type="primary" @click="goBack">返回咨询核对其他依据</el-button>
            <details v-if="detail.content_hash || detail.source_locator" class="audit-detail"><summary>引用核验信息</summary><template v-if="detail.source_locator"><p>原件定位标识</p><code>{{ detail.source_locator }}</code></template><template v-if="detail.content_hash"><p>内容校验值</p><code>{{ detail.content_hash }}</code></template></details>
          </div>
        </aside>
      </div>
    </DataState>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as clauseApi from '@/api/clause'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
import { statusName, errorText, sourceLocation } from '@/utils/presentation'
const route = useRoute(), router = useRouter()
const loading = ref(false), error = ref(''), detail = ref<clauseApi.ClauseDetail | null>(null)
let request = 0
async function load() {
  const id = ++request; loading.value = true; error.value = ''; detail.value = null
  try { const value = await clauseApi.clauseDetail(route.params.id as string, typeof route.query.session_id === 'string' ? route.query.session_id : undefined); if (id === request) detail.value = value }
  catch (e) { if (id === request) error.value = errorText(e, '该引用不存在、已不适用，或不在当前账号权限范围内。请返回咨询核对其他依据。') }
  finally { if (id === request) loading.value = false }
}
function secretName(value: string) { return ({ public: '公开', internal: '内部', confidential: '机密', secret: '秘密' }[value] || value) }
function tagName(value: string) { return ({ normative_body: '规范正文', normative_annex: '规范附件', issuance_notice: '印发通知', standard_table: '标准表格', form: '业务表单', template: '业务模板', flowchart: '流程图', implementation_guide: '实施指引', reference: '参考资料', raw_asset: '原始素材', article: '条款', paragraph: '段落', table: '表格', row: '表格行', cell: '单元格', slide: '幻灯片', document: '文档', section: '章节', heading: '标题' }[value] || value) }
function goBack() { if (window.history.state?.back) router.back(); else router.push('/library') }
watch(() => [route.params.id, route.query.session_id], load, { immediate: true })
</script>

<style scoped>
.back-links { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; font-size: 12px; }.back-links .el-button { padding-left: 0; }.back-links a { text-decoration: none; }.clause-parent { color: var(--zg-text-secondary); font-size: 12px; }.source-location { margin: 8px 0 0; color: var(--zg-text-secondary); font-size: 12px; line-height: 1.8; }.reading-footer { padding: 16px 24px; border-top: 1px solid var(--zg-border-light); color: var(--zg-text-secondary); font-size: 12px; line-height: 1.8; }.source-link { display: block; margin-top: 16px; font-size: 13px; text-decoration: none; }.audit-detail { margin-top: 20px; color: var(--zg-text-secondary); font-size: 11px; }.audit-detail summary { cursor: pointer; }.audit-detail code { display: block; font-size: 10px; overflow-wrap: anywhere; }
</style>
