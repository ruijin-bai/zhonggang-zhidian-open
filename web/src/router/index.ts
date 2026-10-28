import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/store/user'
import { getCompetitionCapabilities } from '@/api/system'

let competitionDemoEnabled: boolean | null = null

const routes = [
  { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { title: '登录' } },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/home' },
      { path: 'home', name: 'home', component: () => import('@/views/HomeView.vue'), meta: { title: '工作台' } },
      { path: 'qa', name: 'qa', component: () => import('@/views/QAView.vue'), meta: { title: '制度咨询' } },
      { path: 'case', name: 'case', component: () => import('@/views/CaseWorkspace.vue'), meta: { title: '事项办理' } },
      { path: 'library', name: 'library', component: () => import('@/views/RegulationLibrary.vue'), meta: { title: '制度目录' } },
      { path: 'library/:id', name: 'regulation-detail', component: () => import('@/views/RegulationDetail.vue'), meta: { title: '制度详情' } },
      { path: 'clause/:id', name: 'clause', component: () => import('@/views/ClauseDetail.vue'), meta: { title: '引用原文' } },
      { path: 'graph', name: 'graph', component: () => import('@/views/RelationGraph.vue'), meta: { title: '制度关系' } },
      // 驻外业务已纳入统一员工制度库；保留旧地址跳转，避免历史链接失效。
      { path: 'overseas', redirect: '/qa' },
      { path: 'push', name: 'push', component: () => import('@/views/PushCenter.vue'), meta: { title: '更新通知' } },
      { path: 'impact', name: 'impact', component: () => import('@/views/ImpactAnalysis.vue'), meta: { title: '变更影响', roles: ['R2', 'R3', 'R4'] } },
      { path: 'rules', name: 'rules', component: () => import('@/views/RulesWorkbench.vue'), meta: { title: '办理规则', roles: ['R2', 'R3', 'R4'] } },
      { path: 'assets', name: 'assets', component: () => import('@/views/AssetWorkbench.vue'), meta: { title: '资料维护', roles: ['R3', 'R4'] } },
      { path: 'dashboard', name: 'dashboard', component: () => import('@/views/Dashboard.vue'), meta: { title: '运行质量', roles: ['R2', 'R4'] } },
      { path: 'competition-evidence', name: 'competition-evidence', component: () => import('@/views/CompetitionEvidence.vue'), meta: { title: '竞赛验收', roles: ['R4'] } },
      { path: 'review', name: 'review', component: () => import('@/views/ReviewCenter.vue'), meta: { title: '审核中心', roles: ['R2', 'R4'] } },
      { path: 'admin', name: 'admin', component: () => import('@/views/admin/AdminView.vue'), meta: { title: '运营管理', roles: ['R3', 'R4'] } },
      { path: 'competition-demo', name: 'competition-demo', component: () => import('@/views/CompetitionDemo.vue'), meta: { title: '演示导航', roles: ['R4'], competitionDemo: true } },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/home' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const user = useUserStore()
  if (to.meta.requiresAuth) {
    if (!user.isLoggedIn) return { name: 'login', query: { redirect: to.fullPath } }
    if (!user.userInfo) {
      try {
        await user.fetchMe()
      } catch {
        user.logout()
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }
  }
  const roles = to.meta.roles as string[] | undefined
  if (roles && !roles.includes(user.role)) {
    return { name: 'home' }
  }
  if (to.meta.competitionDemo) {
    if (competitionDemoEnabled === null) {
      try {
        competitionDemoEnabled = (await getCompetitionCapabilities()).competition_demo_enabled
      } catch {
        competitionDemoEnabled = false
      }
    }
    if (!competitionDemoEnabled) return { name: 'home' }
  }
  return true
})

export default router

router.afterEach((to) => { document.title = `${to.meta.title || '中港智典'} · 中港智典` })
