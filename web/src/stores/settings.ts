import { ref } from 'vue'
import { defineStore } from 'pinia'
import { api, errText } from '@/api'
import type { Settings } from '@/api/types'

// ⑥ 设置页状态。默认值与 app/models.py 的 Settings 保持一致，
// 后端未启动时页面仍可用（能看能改，只是存不上）。

export const defaultSettings: Settings = {
  out_dir: '',
  images_root: '',
  class_name: '',
  exam_title: '',
  keep_images: false,
  auto_open_after_generate: true,
  font_name: '宋体',
  body_size: 10.5,
  line_spacing: 1.1,
  page_margin_cm: 1.27,
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<Settings>({ ...defaultSettings })
  const loading = ref(false)
  const saving = ref(false)
  const loaded = ref(false)
  const error = ref('')

  /** GET /api/settings */
  async function load(): Promise<boolean> {
    loading.value = true
    error.value = ''
    try {
      const s = await api.getSettings()
      settings.value = { ...defaultSettings, ...s }
      loaded.value = true
      return true
    } catch (e) {
      error.value = errText(e)
      return false
    } finally {
      loading.value = false
    }
  }

  /** PUT /api/settings */
  async function save(): Promise<boolean> {
    saving.value = true
    error.value = ''
    try {
      const s = await api.putSettings(settings.value)
      settings.value = { ...defaultSettings, ...s }
      loaded.value = true
      return true
    } catch (e) {
      error.value = errText(e)
      return false
    } finally {
      saving.value = false
    }
  }

  function patch(p: Partial<Settings>) {
    settings.value = { ...settings.value, ...p }
  }

  function restoreDefaults() {
    settings.value = { ...defaultSettings }
  }

  return { settings, loading, saving, loaded, error, load, save, patch, restoreDefaults }
})
