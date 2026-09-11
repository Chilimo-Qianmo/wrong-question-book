<script setup lang="ts">
import { ref } from 'vue'
import { api, errText } from '@/api'
import type { PickKind } from '@/api/types'
import { useUiStore } from '@/stores/ui'

// 选择文件/目录按钮：调用后端原生对话框 POST /api/dialog/pick
const props = withDefaults(
  defineProps<{
    kind: PickKind
    label: string
    title?: string
    multi?: boolean
    initialdir?: string
    variant?: string
    disabled?: boolean
  }>(),
  { title: '', multi: false, initialdir: '', variant: '', disabled: false },
)

const emit = defineEmits<{ (e: 'picked', paths: string[]): void }>()

const ui = useUiStore()
const busy = ref(false)

async function pick() {
  if (busy.value) return
  busy.value = true
  try {
    const r = await api.pick({
      kind: props.kind,
      title: props.title || props.label,
      multi: props.multi,
      initialdir: props.initialdir || '',
    })
    const paths = r && r.paths ? r.paths : []
    if (!paths.length) {
      ui.notify('没有选择任何文件（后端也可能运行在无图形界面的环境中）', 'warn')
      return
    }
    emit('picked', paths)
  } catch (e) {
    ui.notify(errText(e), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button class="btn" :class="variant" :disabled="busy || disabled" @click="pick">
    <span v-if="busy" class="spinner"></span>
    {{ label }}
  </button>
</template>
