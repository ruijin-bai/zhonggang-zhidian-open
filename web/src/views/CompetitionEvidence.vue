<template>
  <div class="zg-container evidence-page" v-loading="loading">
    <PageHeader title="竞赛验收" description="对照正式评分要求，核对已有证据和下一步补证工作。"><template #actions><span class="hint">{{ refreshedAt ? `本次读取 ${refreshedAt}` : '尚未读取' }}</span><el-button @click="load">刷新证据</el-button></template></PageHeader>
    <DataState :error="error" @retry="load">
      <div class="submission-note"><strong>成果提交：10月13日24:00（北京时间）</strong><span>6项必交材料；真实运行视频不超过8分钟。成绩由评审认定，本页不预测得分。</span></div>
      <section class="evidence-section"><h2>正式评分 <small>来源：附件1 参赛方向，全部方向通用，总分100</small></h2><el-table :data="rubric" border size="small"><el-table-column prop="label" label="维度" width="130"/><el-table-column prop="points" label="分值" width="70" align="right"/><el-table-column prop="criteria" label="评分子项" min-width="350"/><el-table-column prop="evidence" label="对应证据" min-width="330"/></el-table></section>
      <el-tabs v-model="tab"><el-tab-pane label="补证工作" name="gaps"><section class="evidence-section"><h2>综合办公规定动作 <small>初选所报方向；赛事联络人与办公室负责确认</small></h2><el-table :data="officialRequirements" border><el-table-column prop="label" label="正式要求" min-width="240"/><el-table-column prop="status" label="当前登记状态" width="180"/><el-table-column prop="action" label="应补材料" min-width="420"/></el-table><p class="table-note">真实问题数量、签审测试题与实际工作样本是不同口径，不能互相替代。要求来源：附件1 综合办公类规定动作与约束条件。</p></section>
        <section class="evidence-section"><h2>项目证据目标 <small>{{ readinessText }}；团队自定目标，不是评分条款</small></h2><el-table :data="data?.award_readiness?.items || []" border size="small"><el-table-column prop="label" label="证据项" min-width="170"/><el-table-column label="记录 / 目标" width="130"><template #default="{ row }">{{ format(row.current) }} / {{ row.target }}</template></el-table-column><el-table-column label="状态" width="95"><template #default="{ row }"><span :class="row.passed ? 'pass' : 'pending'">{{ row.passed ? '达到目标' : '待补证' }}</span></template></el-table-column><el-table-column prop="owner" label="责任岗位" min-width="160"/><el-table-column prop="action" label="下一步" min-width="290"/></el-table><p class="table-note">达到样本量仍需业务审核与真实效果验证。制度原件、审批规则、专家签审与业务部门意见只能由责任人确认。</p></section>
      </el-tab-pane><el-tab-pane label="实际结果" name="results"><p class="scope-note">{{ data?.trial?.disclaimer || '尚未读取试用记录' }} 当前汇总未提供统计起止日期，提交材料时须补充统计周期与样本口径。</p><section class="evidence-section"><h2>真实使用 <small>问题 {{ format(data?.trial?.real_questions) }} 条；配对计时 {{ format(data?.trial?.benchmark_records) }} 组</small></h2><el-table :data="trialMetrics" border><el-table-column prop="label" label="指标" min-width="180"/><el-table-column label="结果" width="150" align="right"><template #default="{ row }">{{ format(row.value, row.kind) }}</template></el-table-column><el-table-column prop="note" label="数据口径" min-width="360"/></el-table></section><section class="evidence-section"><h2>专家签审评测 <small>签审样本 {{ format(data?.golden?.expert_reviewed_total) }} 题</small></h2><el-table :data="goldenMetrics" border><el-table-column prop="label" label="指标" min-width="180"/><el-table-column label="结果" width="150" align="right"><template #default="{ row }">{{ format(row.value, row.kind) }}</template></el-table-column><el-table-column prop="note" label="口径" min-width="360"/></el-table><p class="table-note">{{ data?.golden?.disclaimer }}</p></section></el-tab-pane>
      <el-tab-pane label="场景验证" name="scenarios"><p class="scope-note">{{ data?.scenario_validation?.disclaimer || '验证结果仅表示系统证据完整性，不能替代业务验收。' }}</p><el-table :data="data?.scenario_validation?.scenarios || []" border><el-table-column prop="label" label="场景" min-width="220"/><el-table-column label="现行审核规则" width="125" align="right"><template #default="{ row }">{{ format(row.counts?.reviewed_current_rules) }}</template></el-table-column><el-table-column label="验证结果" width="110"><template #default="{ row }"><span :class="row.status === 'PASS' ? 'pass' : 'pending'">{{ row.status === 'PASS' ? '证据齐备' : '证据待补' }}</span></template></el-table-column><el-table-column label="具体缺口" min-width="380"><template #default="{ row }">{{ formatGaps(row.gaps) }}</template></el-table-column></el-table><div class="follow-links"><router-link to="/rules">补充办理规则</router-link><router-link to="/impact">处理版本影响</router-link><router-link to="/admin">核对制度来源</router-link></div></el-tab-pane>
      <el-tab-pane label="交付核对" name="delivery"><section class="evidence-section"><h2>必交材料 <small>9月30日提交通知；本页未接入文件交付状态</small></h2><el-table :data="delivery" border><el-table-column prop="label" label="材料" width="210"/><el-table-column prop="note" label="内容要求" min-width="500"/></el-table></section><section class="evidence-section"><h2>运行与复现证据</h2><dl class="engineering"><dt>版本结构</dt><dd>{{ migrationText }}</dd><dt>本次后端测试</dt><dd>{{ format(data?.engineering?.backend_tests_passed) }}<small>以实际发布执行记录为准</small></dd><dt>成效材料</dt><dd>选交，须有前后对比、数据口径，可附业务部门确认</dd><dt>脱敏复核</dt><dd>录屏、截图、应用报告与源码均需检查敏感信息展示边界</dd></dl></section></el-tab-pane></el-tabs>
    </DataState>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import * as competitionApi from '@/api/competition'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
const loading = ref(false), error = ref(''), refreshedAt = ref(''), tab = ref('gaps')
const data = ref<any>(null)
const rubric = [
  { label: '业务价值', points: 30, criteria: '场景真实性10 · 问题针对性10 · 预期效益10', evidence: '真实业务问题、人工现状、配对计时与业务确认' },
  { label: '技术实现', points: 25, criteria: '方案可行性8 · 交融与一数一源10 · 系统稳定性7', evidence: '来源台账、真实交融链路、权限和运行复现' },
  { label: '创新性', points: 20, criteria: '思路创新10 · 方法创新10', evidence: '跨制度依据、审核规则、版本变化落实到事项' },
  { label: '可落地性', points: 15, criteria: '实施可行性8 · 推广价值7', evidence: '实际费用、试点范围、维护责任与复制条件' },
  { label: '规范合规', points: 10, criteria: '数据安全5 · 材料完整规范5', evidence: '脱敏、安全核对、真实结果与6项必交材料' },
]
const officialRequirements = [
  { label: '至少3个日常工作环节', status: '待登记业务确认', action: '将制度咨询、事项准备、更新落实逐项列出输入、输出和岗位，提交确认' },
  { label: '不少于30个实际工作样本', status: '待登记样本验收', action: '提供真实工作样本编号、覆盖环节、人工复核和前后对比，避免重复计数' },
  { label: '公司办公室审核验收', status: '待登记审核意见', action: '由办公室确认实用价值、使用范围与推广条件，保留可核验意见' },
  { label: '信息安全与模型合规', status: '待登记展示复核', action: '核对交融对接、信息安全、数据展示边界；对外内容经人工审核' },
]
const delivery = [
  { label: '复选申请表', note: '重新填写实际实现、模型平台、数据、过程、状态、成效、费用与成员实际分工' },
  { label: '应用报告', note: '痛点及现状、方案、数据来源、交融对接、开发测试与推广计划' },
  { label: '真实视频与截图', note: '真实运行、配音讲解、MP4，建议1080p，时长≤8分钟；附关键界面截图' },
  { label: '汇报PPT', note: '问题、方案、成效、推广四方面' },
  { label: '部署说明', note: '运行环境、部署步骤、平台模型依赖与使用方法' },
  { label: '完整源代码', note: '完整可复现源码；无独立源码的平台作品交配置导出或搭建说明' },
]
const gapLabels: Record<string, string> = { authoritative_source: '权威制度来源', reviewed_current_rules: '现行审核规则', amount_currency_boundary: '金额币种与边界', approval_path_and_materials: '审批路径与材料', no_unexplained_conflict: '规则冲突解释', decision_snapshot: '真实事项依据记录', golden_case_coverage: '签审问题覆盖', version_impact_cycle: '版本变化与落实记录' }
const readinessText = computed(() => data.value?.award_readiness ? `${data.value.award_readiness.passed_total}/${data.value.award_readiness.gate_total}项达到目标` : '尚未读取')
const trialMetrics = computed(() => [
  { label: '参与人数', value: data.value?.trial?.trial_participants, note: '真实试用独立账号去重', kind: 'number' },
  { label: '正向反馈率', value: data.value?.trial?.real_questions > 0 ? data.value.trial.positive_feedback_rate : null, note: '有点赞的试用会话 / 有实际回答的试用会话，按会话去重', kind: 'rate' },
  { label: '纠错率', value: data.value?.trial?.real_questions > 0 ? data.value.trial.correction_rate : null, note: '有纠错的试用会话 / 有实际回答的试用会话，按会话去重', kind: 'rate' },
  { label: '人工平均耗时', value: data.value?.trial?.comparable_benchmark_records > 0 ? data.value.trial.manual_avg_seconds : null, note: '仅双方成功且找到依据的同题配对记录', kind: 'seconds' },
  { label: '系统平均耗时', value: data.value?.trial?.comparable_benchmark_records > 0 ? data.value.trial.ai_avg_seconds : null, note: '仅双方成功且找到依据的同题配对记录', kind: 'seconds' },
  { label: '平均节省时间', value: data.value?.trial?.comparable_benchmark_records > 0 ? data.value.trial.avg_saved_seconds : null, note: '成功配对的人工均值减系统均值，可为负数', kind: 'seconds' },
  { label: '效率改善', value: data.value?.trial?.comparable_benchmark_records > 0 && data.value.trial.manual_avg_seconds > 0 ? data.value.trial.efficiency_improvement_rate : null, note: '成功配对的节省时间 / 人工平均耗时', kind: 'rate' },
])
const goldenMetrics = computed(() => { const m = data.value?.golden?.result_available ? data.value?.golden?.metrics : null; return [
  { label: '业务答案通过率', value: m?.business_answer_accuracy, note: '业务专家签审标准，区别于检索召回率', kind: 'rate' },
  { label: '引用精度', value: m?.citation_precision, note: '引用是否支持对应结论', kind: 'rate' },
  { label: '逐结论依据率', value: m?.claim_grounding_rate, note: '结论具备可核验依据', kind: 'rate' },
  { label: '正确转办率', value: m?.refusal_accuracy, note: '应拒答或转人工的问题得到正确处理', kind: 'rate' },
  { label: '越权泄露率', value: m?.permission_leakage_rate, note: '经过越权测试的样本；验收目标为0', kind: 'rate' },
] })
const migrationText = computed(() => { const m = data.value?.engineering?.migration; return !m ? '未采集' : m.single_root_single_head ? `版本结构一致（${m.revision_count}个版本）` : '版本结构需要检查' })
function format(value: unknown, kind = 'number') { if (value === null || value === undefined || (typeof value === 'number' && !Number.isFinite(value))) return '未采集'; if (kind === 'rate') return `${(Number(value) * 100).toFixed(1)}%`; if (kind === 'seconds') return `${Number(value).toFixed(1)} 秒`; return String(value) }
function formatGaps(gaps: string[]) { return gaps?.length ? gaps.map((key) => gapLabels[key] || key).join('、') : '本次系统检查无缺口，仍需业务验收' }
async function load() { if (loading.value) return; loading.value = true; error.value = ''; try { data.value = await competitionApi.evidence(); refreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) } catch { error.value = '竞赛证据读取失败，请重试。' } finally { loading.value = false } }
onMounted(load)
</script>
<style scoped>
.evidence-page{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.evidence-page>*{min-width:0}.submission-note{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap;padding:16px 0;font-size:13px;line-height:1.8}.submission-note span,.scope-note,.table-note{color:var(--zg-text-secondary)}.evidence-section{min-width:0;border:1px solid var(--zg-border);background:#fff;margin:16px 0}.evidence-section h2{margin:0;padding:14px 16px;font-size:15px;border-bottom:1px solid var(--zg-border)}.evidence-section small{font-size:12px;font-weight:400;color:var(--zg-text-secondary);margin-left:10px}.scope-note,.table-note{font-size:12px;line-height:1.8}.table-note{padding:0 16px}.pass{color:#397553}.pending{color:#8a5a00}.follow-links{display:flex;flex-wrap:wrap;gap:20px;margin:18px 0}.engineering{display:grid;grid-template-columns:160px minmax(0,1fr);gap:18px;padding:4px 16px;font-size:13px}.engineering dt{color:var(--zg-text-secondary)}.engineering dd{margin:0;line-height:1.7;overflow-wrap:anywhere}@media(max-width:600px){.engineering{grid-template-columns:minmax(0,1fr);gap:8px}.engineering dd{margin-bottom:10px}.evidence-section h2 small{display:block;margin:6px 0 0}}
</style>
