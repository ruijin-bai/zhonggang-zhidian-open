import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as pushApi from '@/api/push'
import type { PushRecordOut } from '@/api/push'

interface PushCenter {
  pushes: PushRecordOut[]
  total_unread: number
}

/** Pinia store for the update-push center (T13). */
export const usePushStore = defineStore('push', () => {
  const center = ref<PushCenter | null>(null)
  const loading = ref(false)
  let requestVersion = 0

  async function load() {
    const version = ++requestVersion
    loading.value = true
    try {
      const result = await pushApi.center()
      if (version === requestVersion) center.value = result
    } finally {
      if (version === requestVersion) loading.value = false
    }
  }

  async function markRead(pushId: string) {
    await pushApi.markRead(pushId, true)
    await load()
  }

  async function markAllRead(pushIds?: string[]) {
    await pushApi.markReadBatch(pushIds, true)
    await load()
  }

  function clear() {
    ++requestVersion
    center.value = null
    loading.value = false
  }

  return { center, loading, load, markRead, markAllRead, clear }
})
