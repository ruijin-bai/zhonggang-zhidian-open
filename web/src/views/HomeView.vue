<template>
  <div class="zg-container home-page" v-loading="loading">
    <PageHeader :title="roleTitle" :description="roleHint"><template #actions><span class="today">{{ todayText }}</span></template></PageHeader>
    <section class="search-strip" aria-label="快速制度咨询">
      <label for="home-query">遇到业务问题，先找依据</label>
      <div class="search-row"><el-input id="home-query" v-model="quickQuery" clearable placeholder="描述要办的事，或输入制度名称" @keyup.enter="goQA" /><el-button type="primary" @click="goQA">咨询制度</el-button></div>
      <div class="search-examples"><span>也可以直接</span><router-link to="/library">查阅制度原文</router-link><span>或</span><router-link to="/case?new=1">新建办理事项</router-link></div>
    </section>
    <DataState :error="error" @retry="load">
      <div class="home-grid">
        <section class="work-panel">
          <div class="panel-head"><span>{{ user.role === 'R1' ? '我的待办' : '需要处理' }}</span><small>只显示当前账号可处理的任务</small></div>
          <router-link v-for="item in actions" :key="item.label" :to="item.route" class="action-row">
            <div><strong>{{ item.label }}</strong><small>{{ item.note }}</small></div>
            <span :class="['task-count', { warn: item.count > 0 }]">{{ loaded ? item.count : '—' }}<small>项</small></span><span class="arrow">›</span>
          </router-link>
          <p v-if="loaded && actions.every(item => !item.count)" class="all-clear">当前没有待处理任务。可查询制度、查看已办事项或阅读历史更新。</p>
        </section>
        <section class="work-panel">
          <div class="panel-head"><span>{{ user.role === 'R1' ? '从咨询到办事' : '本岗位工作路径' }}</span></div>
          <div class="journey-list">
            <router-link v-for="(item, index) in journey" :key="item.label" :to="item.route"><span class="step-number">{{ index + 1 }}</span><div><strong>{{ item.label }}</strong><p>{{ item.note }}</p></div><span class="arrow">›</span></router-link>
          </div>
        </section>
      </div>
      <section v-if="loaded" class="availability">
        <span>可查看制度与资料 <b>{{ summary.regulation_total }}</b> 份</span>
        <span>我的事项 <b>{{ summary.my_case_total }}</b> 项</span>
        <router-link v-if="['R2', 'R4'].includes(user.role)" to="/dashboard">查看运行质量</router-link>
        <span class="scope-note">数量来自当前权限范围；可查看资料仍须核对来源和生效信息。</span>
      </section>
    </DataState>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import * as dashboardApi from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import DataState from '@/components/DataState.vue'
import { errorText } from '@/utils/presentation'
const router = useRouter(), user = useUserStore()
const quickQuery = ref(''), loading = ref(false), loaded = ref(false), error = ref('')
const summary = ref<Partial<dashboardApi.WorkbenchSummary>>({})
const roleTitle = computed(() => ({ R1: '我的工作台', R2: '审核工作台', R3: '知识维护工作台', R4: '管理工作台' }[user.role] || '工作台'))
const roleHint = computed(() => ({
  R1: '查适用制度、准备办理材料、跟进复核结果与制度更新。',
  R2: '先核对依据，再审核制度、办理规则、待复核事项和纠错反馈。',
  R3: '整理资料、本人确认来源并启用，继续维护员工可用的办理规则。',
  R4: '维护资料与办理规则，处理运行问题、复核待办和制度变更。',
}[user.role] || ''))
const todayText = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Africa/Lagos', month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())
const actions = computed(() => {
  const s = summary.value
  const myTasks = [
    { label: '办理中的事项', note: '查看进展与复核结果', count: s.my_case_open || 0, route: '/case' },
    { label: '未读制度更新', note: '核对与本人相关的变更', count: s.unread_pushes || 0, route: '/push?filter=unread' },
  ]
  if (user.role === 'R1') return myTasks
  if (user.role === 'R2') return [
    { label: '待审制度', note: '核对来源和正文后决定发布', count: s.pending_regulation_reviews || 0, route: '/review?tab=regulation' },
    { label: '待审资料', note: '核对多文件资料和正式来源', count: s.pending_asset_reviews || 0, route: '/review?tab=asset' },
    { label: '待审办理规则', note: '检查条件、审批路径和材料', count: s.pending_rule_reviews || 0, route: '/review?tab=rule' },
    { label: '待复核事项', note: '补足可执行路径并反馈发起人', count: s.pending_case_reviews || 0, route: '/review?tab=case' },
    { label: '待处理纠错', note: '核查问题并记录处理意见', count: s.pending_feedbacks || 0, route: '/review?tab=feedback' },
  ]
  if (user.role === 'R3') return [
    { label: '解析失败的资料', note: '查看原因并修复或重试', count: s.ingestion_failures || 0, route: '/admin?tab=ingestion' },
    { label: '待确认办理规则', note: '对照原文本人确认，或查看正式审核进展', count: s.pending_rule_reviews || 0, route: '/rules?tab=pending' },
    { label: '待处置的变更', note: '检查规则和历史事项的影响', count: s.impact_open || 0, route: '/impact' },
    myTasks[1]!,
  ]
  return [
    { label: '待审核任务', note: '制度、资料、规则、事项与纠错集中处理', count: (s.pending_regulation_reviews || 0) + (s.pending_asset_reviews || 0) + (s.pending_rule_reviews || 0) + (s.pending_case_reviews || 0) + (s.pending_feedbacks || 0), route: '/review' },
    { label: '解析失败的资料', note: '定位影响制度可用性的处理问题', count: s.ingestion_failures || 0, route: '/admin?tab=ingestion' },
    { label: '待处置的变更', note: '处理风险后确认闭环', count: s.impact_open || 0, route: '/impact' },
    myTasks[1]!,
  ]
})
const journey = computed(() => {
  if (user.role === 'R1') return [
    { label: '找依据', note: '描述场景，补充必要条件，核对原文。', route: '/qa' },
    { label: '准备办理', note: '填写事实，按已确认规则生成路径；缺依据时转人工。', route: '/case?new=1' },
    { label: '跟进更新', note: '查看制度变更，确认阅读，再落实办理要求。', route: '/push' },
  ]
  if (user.role === 'R2') return [
    { label: '核对待审原文', note: '确认来源、版本及适用范围。', route: '/review?tab=regulation' },
    { label: '审核可执行规则', note: '检查规则条件与原文是否一致。', route: '/rules?tab=pending' },
    { label: '复核具体事项', note: '给出明确意见、审批路径和材料。', route: '/case?tab=queue' },
  ]
  if (user.role === 'R3') return [
    { label: '整理制度资料', note: '管理正文、附件和解析结果。', route: '/assets' },
    { label: '本人确认来源', note: '批量确认上传资料；文号、部门和日期按需补充。', route: '/admin?tab=regulations' },
    { label: '维护办理规则', note: '对照原文确认后启用，正式审核可选。', route: '/rules' },
  ]
  return [
    { label: '启用制度资料', note: '整理正文与附件，本人确认后提供员工使用。', route: '/assets' },
    { label: '维护办理规则', note: '对照原文确认路径与材料，直接启用或送正式审核。', route: '/rules' },
    { label: '跟进制度变更', note: '查看受影响规则和历史事项，记录处理结果。', route: '/impact' },
  ]
})
function goQA() { const q = quickQuery.value.trim(); router.push(q ? { path: '/qa', query: { q, ask: '1' } } : '/qa') }
async function load() { loading.value = true; error.value = ''; try { summary.value = await dashboardApi.workbench(); loaded.value = true } catch (e) { error.value = errorText(e); loaded.value = false } finally { loading.value = false } }
onMounted(load)
</script>

<style scoped>
.home-page { display: flex; flex-direction: column; gap: 20px; }.home-page :deep(.zg-page-header) { margin-bottom: 0; }.today { color: var(--zg-text-secondary); font-size: 12px; }
.search-strip { padding: 20px; border: 1px solid var(--zg-border); border-top: 3px solid var(--zg-primary); background: #fff; }.search-strip label { display: block; margin-bottom: 12px; font-size: 15px; font-weight: 600; }.search-row { display: flex; gap: 8px; }.search-row :deep(.el-input__wrapper) { min-height: 38px; }.search-row .el-button { min-height: 38px; }.search-examples { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; color: var(--zg-text-secondary); font-size: 12px; }.search-examples a { text-decoration: none; }
.home-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.action-row { display: flex; align-items: center; gap: 16px; min-height: 77px; padding: 14px 18px; border-bottom: 1px solid var(--zg-border-light); color: var(--zg-text); text-decoration: none; }.action-row:hover { background: var(--zg-primary-soft); }.action-row > div { flex: 1; }.action-row strong { font-size: 13px; font-weight: 600; }.action-row small { display: block; margin-top: 5px; color: var(--zg-text-secondary); font-size: 12px; }.task-count { display: flex; align-items: baseline; gap: 4px; font-size: 21px; font-weight: 500; }.task-count small { font-weight: 400; }.task-count.warn { color: #956817; }.arrow { color: var(--zg-text-secondary); }.all-clear { margin: 0; padding: 14px 18px; color: var(--zg-text-secondary); font-size: 12px; line-height: 1.7; }
.journey-list a { display: flex; align-items: center; gap: 12px; min-height: 100px; padding: 16px 18px; border-bottom: 1px solid var(--zg-border-light); color: var(--zg-text); text-decoration: none; }.journey-list a:hover { background: var(--zg-panel-soft); }.journey-list a > div { flex: 1; }.journey-list strong { font-size: 13px; }.journey-list p { margin: 6px 0 0; color: var(--zg-text-secondary); font-size: 12px; line-height: 1.7; }.step-number { display: grid; width: 26px; height: 26px; place-items: center; border: 1px solid var(--zg-border); color: var(--zg-primary); font-size: 12px; }
.availability { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; padding: 16px 0; color: var(--zg-text-secondary); font-size: 12px; }.availability b { color: var(--zg-text); font-weight: 600; }.scope-note { flex-basis: 100%; }
@media (max-width: 1000px) { .home-grid { grid-template-columns: 1fr; } }
</style>
