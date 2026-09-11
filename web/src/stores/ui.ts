import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api'
import type { HealthInfo } from '@/api/types'

export type ToastType = 'info' | 'success' | 'warn' | 'error'

export interface Toast {
  id: number
  text: string
  type: ToastType
}

/** 全局轻提示 + 后端健康状态 */
export const useUiStore = defineStore('ui', () => {
  const toasts = ref<Toast[]>([])
  const online = ref<boolean | null>(null) // null=尚未检测
  const version = ref('')
  const engine = ref<HealthInfo['engine'] | null>(null)
  let seq = 0

  function notify(text: string, type: ToastType = 'info', ms = 4500) {
    const id = ++seq
    toasts.value.push({ id, text, type })
    window.setTimeout(() => dismiss(id), ms)
  }

  function dismiss(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  async function checkHealth() {
    try {
      const h = await api.health()
      online.value = !!h.ok
      version.value = h.version || ''
      engine.value = h.engine || null
    } catch {
      online.value = false
      version.value = ''
      engine.value = null
    }
  }

  return { toasts, online, version, engine, notify, dismiss, checkHealth }
})
