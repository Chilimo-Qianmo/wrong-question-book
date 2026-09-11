<script setup lang="ts">
import { computed } from 'vue'

// 任务进度条
const props = withDefaults(
  defineProps<{ percent: number; label?: string; stage?: string }>(),
  { label: '', stage: '' },
)

const value = computed(() => {
  const p = Number(props.percent)
  if (!isFinite(p)) return 0
  return Math.max(0, Math.min(100, p))
})
</script>

<template>
  <div class="pb">
    <div class="pbhead">
      <span class="pblabel">{{ label || '进度' }}</span>
      <span class="pbnum">{{ Math.round(value) }}%</span>
    </div>
    <div class="progress"><i :style="{ width: value + '%' }"></i></div>
    <div v-if="stage" class="pbstage">阶段：{{ stage }}</div>
  </div>
</template>

<style scoped>
.pb {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pbhead {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--c-text-2);
}
.pbnum {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--c-primary);
}
.pbstage {
  font-size: 12px;
  color: var(--c-text-3);
}
</style>
