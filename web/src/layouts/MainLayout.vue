<template>
  <div class="app-shell" :class="{ 'nav-open': navOpen }">
    <button v-if="navOpen" class="nav-scrim" aria-label="关闭导航" @click="navOpen = false" />
    <aside class="app-nav" aria-label="主导航">
      <router-link to="/home" class="brand" @click="navOpen = false"><span class="brand-mark">中</span><span>中港智典<small>制度与业务工作平台</small></span></router-link>
      <nav>
        <section v-for="group in navigation" :key="group.title" class="nav-group">
          <div class="nav-group-title">{{ group.title }}</div>
          <router-link v-for="item in group.items" :key="item.path" :to="item.path" :class="{ selected: isActive(item.path) }" :aria-current="isActive(item.path) ? 'page' : undefined" @click="navOpen = false">
            <span>{{ item.label }}</span><span v-if="item.count && summaryReady" class="nav-count">{{ item.count > 99 ? '99+' : item.count }}</span>
          </router-link>
        </section>
      </nav>
      <div class="nav-account"><strong>{{ roleName }}</strong><span>按账号权限显示资料</span></div>
    </aside>
    <div class="app-body">
      <header class="app-topbar">
        <div class="location"><button class="nav-toggle" aria-label="打开导航" :aria-expanded="navOpen" @click="navOpen = !navOpen">☰</button><span class="location-group">{{ currentGroup }}</span><span class="location-divider">/</span><span>{{ pageTitle }}</span></div>
        <div class="user-box"><span>{{ user.userInfo?.username }}</span><span class="user-role">{{ roleName }}</span><el-button text @click="onLogout">退出</el-button></div>
      </header>
      <main id="main-content" class="app-main"><router-view /></main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import * as dashboardApi from '@/api/dashboard'
import { roleNames } from '@/utils/presentation'
const route = useRoute(), router = useRouter(), user = useUserStore()
const navOpen = ref(false), summary = ref<Partial<dashboardApi.WorkbenchSummary>>({}), summaryReady = ref(false)
const canGovern = computed(() => ['R2', 'R3', 'R4'].includes(user.role))
const canMaintain = computed(() => ['R3', 'R4'].includes(user.role))
const canReview = computed(() => ['R2', 'R4'].includes(user.role))
const roleName = computed(() => roleNames[user.role] || '已授权用户')
const pageTitle = computed(() => route.meta.title || '工作台')
const reviewCount = computed(() => (summary.value.pending_regulation_reviews || 0) + (summary.value.pending_asset_reviews || 0) + (summary.value.pending_rule_reviews || 0) + (summary.value.pending_case_reviews || 0) + (summary.value.pending_feedbacks || 0))
const navigation = computed(() => {
  const groups = [{ title: '日常工作', items: [
    { path: '/home', label: '工作台', count: 0 }, { path: '/qa', label: '制度咨询', count: 0 },
    { path: '/case', label: '事项办理', count: summary.value.my_case_open || 0 },
    { path: '/library', label: '制度目录', count: 0 }, { path: '/push', label: '更新通知', count: summary.value.unread_pushes || 0 },
  ] }]
  if (canGovern.value) {
    const items = []
    if (canReview.value) items.push({ path: '/review', label: '审核中心', count: reviewCount.value })
    if (canMaintain.value) items.push({ path: '/assets', label: '资料维护', count: 0 })
    items.push({ path: '/rules', label: '办理规则', count: summary.value.pending_rule_reviews || 0 }, { path: '/impact', label: '变更影响', count: summary.value.impact_open || 0 }, { path: '/graph', label: '制度关系', count: 0 })
    groups.push({ title: '制度治理', items })
  }
  const operations = []
  if (canReview.value) operations.push({ path: '/dashboard', label: '运行质量', count: 0 })
  if (canMaintain.value) operations.push({ path: '/admin', label: '运营管理', count: summary.value.ingestion_failures || 0 })
  if (user.role === 'R4') operations.push({ path: '/competition-evidence', label: '竞赛验收', count: 0 })
  if (operations.length) groups.push({ title: '运营与验收', items: operations })
  return groups
})
function isActive(path: string) { return route.path === path || (path === '/library' && (route.path.startsWith('/library/') || route.path.startsWith('/clause/'))) }
const currentGroup = computed(() => navigation.value.find(group => group.items.some(item => isActive(item.path)))?.title || '运营与验收')
function onLogout() { user.logout(); router.push('/login') }
let request = 0
async function refreshSummary() {
  const id = ++request
  try { const value = await dashboardApi.workbench(); if (id === request) { summary.value = value; summaryReady.value = true } }
  catch { if (id === request) summaryReady.value = false }
}
watch(() => route.fullPath, () => { navOpen.value = false; void refreshSummary() }, { immediate: true })
onMounted(() => window.addEventListener('zg-workbench-changed', refreshSummary))
onUnmounted(() => { ++request; window.removeEventListener('zg-workbench-changed', refreshSummary) })
</script>

<style scoped>
.app-shell { display: grid; grid-template-columns: 208px minmax(0, 1fr); height: 100dvh; }
.app-nav { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--zg-border); background: #fff; }
.brand { display: flex; align-items: center; gap: 10px; min-height: 76px; padding: 17px 18px; border-bottom: 1px solid var(--zg-border-light); color: var(--zg-text); text-decoration: none; font-size: 18px; font-weight: 600; }
.brand-mark { display: grid; width: 30px; height: 30px; place-items: center; background: var(--zg-primary); color: #fff; font-size: 16px; }
.brand small { display: block; margin-top: 4px; color: var(--zg-text-secondary); font-size: 10px; font-weight: 400; }
nav { flex: 1; min-height: 0; padding: 8px 12px 16px; overflow-y: auto; }
.nav-group { margin-top: 12px; }.nav-group-title { padding: 6px 10px; color: var(--zg-text-secondary); font-size: 11px; }
.nav-group a { display: flex; align-items: center; gap: 8px; min-height: 37px; margin: 2px 0; padding: 7px 10px; border-left: 2px solid transparent; color: #43505d; text-decoration: none; font-size: 13px; }
.nav-group a:hover { background: var(--zg-panel-soft); }.nav-group a.selected { border-left-color: var(--zg-primary); background: var(--zg-primary-soft); color: var(--zg-primary); font-weight: 600; }
.nav-count { margin-left: auto; padding: 1px 5px; background: #f9efdc; color: #8a5a00; font-size: 11px; }
.nav-account { padding: 14px 20px; border-top: 1px solid var(--zg-border-light); font-size: 12px; }.nav-account strong { font-weight: 500; }.nav-account span { display: block; margin-top: 5px; color: var(--zg-text-secondary); font-size: 11px; }
.app-body { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.app-topbar { display: flex; flex-shrink: 0; align-items: center; justify-content: space-between; min-height: 56px; gap: 12px; padding: 0 28px; border-bottom: 1px solid var(--zg-border); background: #fff; font-size: 12px; }
.location { display: flex; align-items: center; gap: 10px; min-width: 0; }.location-group { color: var(--zg-text-secondary); }.location-divider { color: #b5bec8; }
.user-box { display: flex; align-items: center; gap: 12px; white-space: nowrap; }.user-role { padding-left: 12px; border-left: 1px solid var(--zg-border); color: var(--zg-text-secondary); }
.app-main { flex: 1; min-height: 0; overflow: auto; }.nav-toggle { display: none; padding: 4px; border: 0; background: none; color: var(--zg-text); font-size: 20px; cursor: pointer; }.nav-scrim { display: none; }
@media (max-width: 900px) {
  .app-shell { grid-template-columns: 1fr; }.app-nav { position: fixed; inset: 0 auto 0 0; z-index: 1001; width: 224px; transform: translateX(-100%); }.nav-open .app-nav { transform: translateX(0); }.nav-scrim { display: block; position: fixed; inset: 0; z-index: 1000; border: 0; background: rgba(20, 30, 40, .3); }.nav-toggle { display: block; }.app-topbar { padding: 0 14px; }.user-role { display: none; }
}
@media (max-width: 480px) { .location-group, .location-divider { display: none; }.user-box { gap: 4px; } }
</style>
