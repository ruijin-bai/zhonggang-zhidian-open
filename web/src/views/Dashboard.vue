<template>
  <div class="zg-container quality-page" v-loading="loading">
    <PageHeader title="运行质量" description="先处理影响员工使用的问题，再查看服务质量与制度覆盖。"><template #actions><span class="hint">{{ refreshedAt ? `本次读取 ${refreshedAt}` : '尚未读取' }}</span><el-button @click="load">刷新</el-button></template></PageHeader>
    <DataState :error="error" @retry="load">
      <p class="scope-note">统计范围：制度、条款、规则和事项按当前数据权限；在线问答、反馈和评测为运行库累计记录。在线指标排除评测回放；零样本显示未采集，服务信号需结合业务专家核对。</p>
      <section class="quality-section"><h2>需要处理</h2><el-table :data="actions" border size="small"><el-table-column prop="label" label="工作" min-width="180"/><el-table-column label="待处理" width="110" align="right"><template #default="{ row }"><b :class="{ warning: row.value > 0 }">{{ count(row.value) }}</b></template></el-table-column><el-table-column prop="note" label="处理目标" min-width="300"/><el-table-column label="入口" width="120"><template #default="{ row }"><router-link :to="row.route">{{ row.action }}</router-link></template></el-table-column></el-table></section>
      <section class="quality-section"><h2>在线问答 <small>累计 {{ count(data?.qa_total) }} 次；有回答 {{ count(data?.answered_total) }} 次</small></h2><el-table :data="qualityRows" border size="small"><el-table-column prop="label" label="信号" min-width="160"/><el-table-column prop="value" label="当前值" width="120" align="right"/><el-table-column prop="scope" label="统计口径" min-width="310"/><el-table-column prop="meaning" label="如何使用" min-width="290"/></el-table></section>
      <section class="quality-section"><h2>制度与规则基础</h2><div class="asset-summary"><div><span>现行制度</span><b>{{ count(data?.regulation_current) }}</b><small>来源已确认 {{ count(data?.regulation_authority_verified) }} 份</small></div><div><span>已解析条款</span><b>{{ count(data?.clause_total) }}</b><small>包含历史与隔离记录</small></div><div><span>可用办理规则</span><b>{{ count(data?.active_rule_count) }}</b><small>当期有效、规则与来源已确认</small></div><div><span>已确认事项</span><b>{{ count(data?.case_confirmed) }}</b><small>累计事项 {{ count(data?.case_total) }} 份</small></div></div></section>
      <div class="quality-pair"><section class="quality-section"><h2>反馈记录 <small>含收藏和点赞</small></h2><el-table :data="feedbackRows" size="small" border empty-text="暂无反馈记录"><el-table-column prop="label" label="反馈类型"/><el-table-column prop="count" label="记录数" width="100" align="right"/></el-table></section><section class="quality-section"><h2>待补评测场景 <small>已有条款标签尚无测试题覆盖</small></h2><el-table :data="uncoveredRows" size="small" border empty-text="暂无待补评测标签"><el-table-column prop="scenario" label="场景标签"/></el-table><p class="table-note">评测台账 {{ count(data?.testset_total) }} 题；评测运行 {{ count(data?.evaluation_run_total) }} 次；检索检查 {{ count(data?.retrieval_smoke_total) }} 题。业务正确性以签审样本另行评测。</p></section></div>
    </DataState>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import * as dashApi from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
const loading = ref(false), error = ref(''), refreshedAt = ref('')
const data = ref<Record<string, any> | null>(null)
const count = (value: unknown) => typeof value === 'number' ? value.toLocaleString() : '未采集'
function rate(key: string, denominator: unknown) { return typeof denominator === 'number' && denominator > 0 && typeof data.value?.[key] === 'number' ? `${(data.value[key] * 100).toFixed(1)}%` : '未采集' }
const actions = computed(() => [
  { label: '高风险变更', value: data.value?.open_high_impact_count, note: '核对受影响规则和事项，再记录实际处置', route: '/impact', action: '处理变更' },
  { label: '待复核事项', value: data.value?.case_review_required, note: '确认适用条件、材料和制度依据', route: '/case?tab=queue', action: '复核事项' },
  { label: '待审核制度', value: data.value?.regulation_pending_review, note: '确认原件、现行版本及责任部门', route: '/review', action: '审核制度' },
  { label: '待审核资料', value: data.value?.pending_asset_reviews, note: '核对正文、附件、生效信息和来源后发布', route: '/review?tab=asset', action: '审核资料' },
  { label: '未处理纠错', value: data.value?.pending_feedback_count, note: '核对员工指出的问题并记录实际处理', route: '/review?tab=feedback', action: '查看纠错' },
])
const qualityRows = computed(() => [
  { label: '返回来源', value: rate('realtime_citation_rate', data.value?.answered_total), scope: '至少有一条来源的会话 / 有回答会话', meaning: '核对引用是否真正支持结论' },
  { label: '结论引用校验', value: rate('grounding_rate', data.value?.answered_total), scope: '通过引用与数字校验的回答 / 有回答会话', meaning: '技术校验通过仍需核对业务适用性' },
  { label: '回答来源确认', value: rate('authority_answer_rate', data.value?.answered_total), scope: '回答时全部依据已确认 / 有回答会话', meaning: '维护者可本人确认可靠来源，正式信息按需补充' },
  { label: '建议人工复核', value: rate('human_handoff_rate', data.value?.qa_total), scope: '需要人工判断的会话 / 在线问答会话', meaning: '结合问题类型查清资料缺口与边界' },
  { label: '原文定位覆盖', value: rate('source_anchor_rate', data.value?.clause_total), scope: '有内容定位标识的条款 / 全部条款', meaning: '用于追溯原文，不代表审批结论正确' },
])
const feedbackRows = computed(() => (data.value?.correction_distribution || []).map((row: { type: string; count: number }) => ({ ...row, label: ({ like: '点赞', favorite: '收藏', correct: '纠错', correction: '纠错' } as Record<string, string>)[row.type] || row.type })))
const uncoveredRows = computed(() => (data.value?.uncovered_scenarios || []).map((scenario: string) => ({ scenario })))
async function load() { if (loading.value) return; loading.value = true; error.value = ''; try { data.value = await dashApi.quality(); refreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) } catch { error.value = '运行质量数据读取失败，请重试。' } finally { loading.value = false } }
onMounted(load)
</script>
<style scoped>
.quality-page{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.quality-page>*{min-width:0}.scope-note,.table-note{color:var(--zg-text-secondary);font-size:12px;line-height:1.7}.quality-section{min-width:0;background:#fff;border:1px solid var(--zg-border);margin-bottom:16px}.quality-section h2{margin:0;padding:12px 16px;font-size:15px;border-bottom:1px solid var(--zg-border)}.quality-section h2 small{margin-left:12px;font-size:12px;font-weight:400;color:var(--zg-text-secondary)}.asset-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}.asset-summary div{min-width:0;overflow-wrap:anywhere;display:grid;gap:8px;padding:16px;border-right:1px solid var(--zg-border)}.asset-summary span,.asset-summary small{color:var(--zg-text-secondary);font-size:12px}.asset-summary b{font-size:24px}.quality-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.table-note{margin:12px 16px}.warning{color:#9a4800}@media(max-width:1000px){.quality-pair{grid-template-columns:minmax(0,1fr)}.asset-summary{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
