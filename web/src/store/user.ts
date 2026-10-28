import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import type { UserInfo } from '@/api/auth'
import { useQaStore } from './qa'
import { usePushStore } from './push'

export const useUserStore = defineStore('user', () => {
  const token = ref<string>(localStorage.getItem('zg_token') || '')
  const role = ref<string>(localStorage.getItem('zg_role') || '')
  const userInfo = ref<UserInfo | null>(null)
  const isLoggedIn = ref<boolean>(!!token.value)

  async function login(username: string, password: string) {
    const data = await authApi.login(username, password)
    useQaStore().clear()
    usePushStore().clear()
    token.value = data.access_token
    role.value = data.user.role
    userInfo.value = data.user
    isLoggedIn.value = true
    localStorage.setItem('zg_token', token.value)
    localStorage.setItem('zg_role', role.value)
  }

  async function fetchMe() {
    userInfo.value = await authApi.me()
    role.value = userInfo.value.role
    localStorage.setItem('zg_role', role.value)
  }

  function logout() {
    useQaStore().clear()
    usePushStore().clear()
    token.value = ''
    role.value = ''
    userInfo.value = null
    isLoggedIn.value = false
    localStorage.removeItem('zg_token')
    localStorage.removeItem('zg_role')
  }

  return { token, role, userInfo, isLoggedIn, login, fetchMe, logout }
})
