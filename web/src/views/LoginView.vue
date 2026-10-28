<template>
  <main class="login-page">
    <div class="login-brand"><span class="brand-mark">中</span><strong>中港智典</strong><span>制度与业务工作平台</span></div>
    <section class="login-panel">
      <div class="login-heading"><h1>登录工作台</h1><p>使用已授权账号，进入本岗位的制度与业务任务。</p></div>
      <el-form label-position="top" @submit.prevent="onLogin">
        <el-form-item label="账号"><el-input v-model="username" autocomplete="username" placeholder="请输入账号" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" autocomplete="current-password" show-password placeholder="请输入密码" /></el-form-item>
        <p v-if="validationError" class="login-error" role="alert">{{ validationError }}</p>
        <el-button native-type="submit" type="primary" :loading="loading" class="login-button">登录</el-button>
      </el-form>
      <section v-if="demoEnabled" class="demo-login" aria-label="开发身份">
        <div class="demo-head">本地开发身份<span>仅开发环境可见</span></div>
        <div class="demo-grid"><button v-for="identity in identities" :key="identity.username" type="button" :class="{ active: username === identity.username }" @click="selectIdentity(identity)"><strong>{{ identity.role_label }}</strong><small>{{ identity.description }}</small></button></div>
        <p>选择身份后点击登录。开发密码不会显示在页面中。</p>
      </section>
      <div class="login-help">账号或权限问题，请联系系统管理员。</div>
    </section>
    <footer>中国港湾工程有限责任公司</footer>
  </main>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/store/user'
import { demoIdentities, type DemoIdentity } from '@/api/auth'
const username = ref(''), password = ref(''), loading = ref(false), validationError = ref('')
const user = useUserStore(), route = useRoute(), router = useRouter()
const demoEnabled = ref(false), identities = ref<DemoIdentity[]>([])
function selectIdentity(identity: DemoIdentity) { username.value = identity.username; password.value = identity.password; validationError.value = '' }
async function onLogin() {
  if (loading.value) return
  validationError.value = ''
  if (!username.value.trim() || !password.value) { validationError.value = '请填写账号和密码。'; return }
  loading.value = true
  try {
    await user.login(username.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    await router.replace(redirect.startsWith('/') && !redirect.startsWith('//') && !redirect.startsWith('/login') ? redirect : '/home')
  } catch { validationError.value = '登录未成功，请核对账号密码，或检查服务是否可用。' }
  finally { loading.value = false }
}
onMounted(async () => { try { const data = await demoIdentities(); demoEnabled.value = data.enabled; identities.value = data.identities } catch { demoEnabled.value = false } })
</script>

<style scoped>
.login-page { display: flex; flex-direction: column; align-items: center; min-height: 100dvh; padding: 58px 20px 24px; background: var(--zg-panel-soft); }
.login-brand { display: flex; align-items: center; gap: 10px; width: min(430px, 100%); margin-bottom: 34px; }.brand-mark { display: grid; width: 32px; height: 32px; place-items: center; background: var(--zg-primary); color: #fff; font-size: 16px; }.login-brand strong { font-size: 19px; }.login-brand > span:last-child { margin-left: auto; color: var(--zg-text-secondary); font-size: 11px; }
.login-panel { width: min(430px, 100%); padding: 28px; border: 1px solid var(--zg-border); border-top: 3px solid var(--zg-primary); background: #fff; }.login-heading { margin-bottom: 24px; }.login-heading h1 { margin: 0; font-size: 22px; line-height: 1.6; }.login-heading p { margin: 8px 0 0; color: var(--zg-text-secondary); font-size: 13px; line-height: 1.7; }.login-panel :deep(.el-input__wrapper) { min-height: 38px; }.login-button { width: 100%; min-height: 40px; }.login-error { color: #aa4236; font-size: 12px; line-height: 1.6; }.login-help { margin-top: 22px; color: var(--zg-text-secondary); font-size: 12px; }
.demo-login { margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--zg-border); }.demo-head { display: flex; justify-content: space-between; color: var(--zg-text); font-size: 12px; }.demo-head span { color: var(--zg-text-secondary); font-size: 11px; }.demo-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 12px; }.demo-grid button { padding: 10px; border: 1px solid var(--zg-border); background: #fff; text-align: left; cursor: pointer; }.demo-grid button:hover, .demo-grid button.active { border-color: var(--zg-primary); background: var(--zg-primary-soft); }.demo-grid strong { font-size: 12px; }.demo-grid small { display: block; margin-top: 5px; color: var(--zg-text-secondary); font-size: 11px; line-height: 1.5; }.demo-login p { color: var(--zg-text-secondary); font-size: 11px; line-height: 1.6; }
footer { margin-top: auto; padding-top: 32px; color: var(--zg-text-secondary); font-size: 11px; }
@media (max-width: 480px) { .login-page { padding-top: 34px; }.login-panel { padding: 22px; }.login-brand > span:last-child { display: none; } }
</style>
