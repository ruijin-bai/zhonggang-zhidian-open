<template>
  <div class="zg-container demo-page" v-loading="loading">
    <PageHeader title="演示导航" description="用一个经过验证的工作场景，展示员工咨询、事项准备和更新落实。"><template #actions><el-button @click="load">重新核对</el-button></template></PageHeader>
    <DataState :error="error" @retry="load">
      <div class="scenario-picker"><label for="demo-scenario">演示场景</label><el-select id="demo-scenario" v-model="scenario" placeholder="选择真实场景" style="width:300px"><el-option v-for="item in scenarios" :key="item.scenario" :value="item.scenario" :label="`${item.label} · ${item.status === 'PASS' ? '证据齐备' : '待补证'}`"/></el-select><el-tag effect="plain" :type="storyReady ? 'success' : 'warning'">{{ storyReady ? '系统证据检查通过' : '尚不具备完整演示证据' }}</el-tag></div>
      <div v-if="!storyReady && !loading" class="missing-note"><h2>先补齐这个场景的证据</h2><p>{{ gapText }}</p><router-link to="/competition-evidence">查看补证工作</router-link></div>
      <p class="scope-note">演示页读取真实记录，不生成答案或代填业务事实。系统检查通过仍需业务部门授权与验收；正式视频只使用已确认、允许展示的样本。</p>
      <ol class="demo-steps"><li v-for="(step, index) in steps" :key="step.title"><span class="step-number">{{ index + 1 }}</span><div><h2>{{ step.title }}</h2><p>{{ step.description }}</p><small>{{ step.check }}</small></div><el-button :type="index === 0 ? 'primary' : 'default'" :disabled="step.requiresPass && !storyReady" @click="router.push(step.route)">{{ step.action }}</el-button></li></ol>
      <section class="recording-note"><h2>录屏核对</h2><p>真实交融链路稳定、问题和引用完整、样本获得授权、画面已脱敏，再进行正式录屏。比赛要求视频≤8分钟；建议围绕同一工作故事控制在5分钟。</p><p>审批路径、金额边界和材料清单由审核规则确定。演示时让用户在业务页确认事实，保留转人工、风险和版本变化的真实状态。</p></section>
    </DataState>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as competitionApi from '@/api/competition'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
interface Scenario { scenario: string; label: string; status: string; gaps: string[] }
const router = useRouter()
const loading = ref(false), error = ref(''), scenario = ref('')
const scenarios = ref<Scenario[]>([])
const selected = computed(() => scenarios.value.find((item) => item.scenario === scenario.value))
const storyReady = computed(() => selected.value?.status === 'PASS')
const gapLabels: Record<string, string> = { authoritative_source: '权威制度来源', reviewed_current_rules: '现行审核规则', amount_currency_boundary: '金额币种边界', approval_path_and_materials: '审批路径与材料', no_unexplained_conflict: '规则冲突说明', decision_snapshot: '真实事项依据', golden_case_coverage: '签审问题', version_impact_cycle: '版本影响记录' }
const gapText = computed(() => selected.value?.gaps.length ? selected.value.gaps.map((key) => gapLabels[key] || key).join('、') : '尚未取得通过验证的场景记录。请选择场景或刷新核对。')
const steps = computed(() => [
  { title: '咨询与核对依据', description: '输入实际工作问题，补齐系统追问的条件，核对适用制度、条款和解释。', check: '缺条件先追问；缺依据保留人工复核，不给无来源结论。', route: '/qa', action: '开始咨询', requiresPass: true },
  { title: '准备办理事项', description: '依据已经审核的规则，确认材料、审批路径和风险，保存事项与依据记录。', check: '演示导航不预填金额、币种或审批结果。', route: `/case?new=1&scenario=${encodeURIComponent(scenario.value)}`, action: '准备事项', requiresPass: true },
  { title: '落实制度更新', description: '展示相关制度版本变化，核对受影响规则和历史事项，查看实际处理记录。', check: '高风险未处置时不能确认闭环；阅读回执与落实记录分开。', route: '/impact', action: '查看变更', requiresPass: true },
  { title: '核对实际成果', description: '展示真实使用、专家签审、配对计时与场景证据，并说明尚未完成的工作。', check: '没有真实样本的指标显示未采集，目标与实测分开。', route: '/competition-evidence', action: '核对证据', requiresPass: false },
])
async function load() { if (loading.value) return; loading.value = true; error.value = ''; try { const result = await competitionApi.evidence(); scenarios.value = result?.scenario_validation?.scenarios || []; if (!scenarios.value.some((item) => item.scenario === scenario.value)) scenario.value = scenarios.value.find((item) => item.status === 'PASS')?.scenario || scenarios.value[0]?.scenario || '' } catch { error.value = '场景验证记录读取失败，请重试。' } finally { loading.value = false } }
onMounted(load)
</script>
<style scoped>
.demo-page{display:grid;grid-template-columns:minmax(0,1fr);gap:16px}.demo-page>*{min-width:0}.scenario-picker{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0;font-size:13px}.scope-note{font-size:12px;color:var(--zg-text-secondary);line-height:1.8}.missing-note{border-bottom:1px solid var(--zg-border);padding:0 0 16px;color:#8a5a00}.missing-note h2{font-size:15px}.missing-note p{font-size:13px;line-height:1.8}.demo-steps{list-style:none;padding:0;border:1px solid var(--zg-border);background:#fff;margin:20px 0}.demo-steps li{display:grid;grid-template-columns:32px minmax(0,1fr) auto;gap:18px;align-items:center;padding:20px;border-bottom:1px solid var(--zg-border)}.demo-steps li:last-child{border-bottom:0}.step-number{font-size:22px;color:var(--zg-primary);font-weight:600}.demo-steps h2{font-size:16px;margin:0 0 8px}.demo-steps p,.recording-note p{font-size:13px;line-height:1.8;margin:0 0 8px}.demo-steps small{color:var(--zg-text-secondary);font-size:12px}.recording-note{border-top:1px solid var(--zg-border);padding-top:8px}.recording-note h2{font-size:15px}@media(max-width:700px){.demo-steps li{grid-template-columns:24px minmax(0,1fr)}.demo-steps li>.el-button{grid-column:2;justify-self:start}}
</style>
