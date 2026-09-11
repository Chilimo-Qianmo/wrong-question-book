<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { LogEvent } from '@/api/types'

// 实时日志面板：带时间戳与级别着色，新日志自动滚到底部
const props = withDefaults(defineProps<{ logs: LogEvent[]; height?: string }>(), { height: '260px' })

const box = ref<HTMLDivElement | null>(null)
const autoScroll = ref(true)

function onScroll() {
  const el = box.value
  if (!el) return
  autoScroll.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

watch(
  () => props.logs.length,
  () => {
    if (!autoScroll.value) return
    void nextTick(() => {
      const el = box.value
      if (el) el.scrollTop = el.scrollHeight
    })
  },
)

function levelClass(level: string): string {
  const l = (level || 'info').toLowerCase()
  if (l === 'warn' || l === 'warning') return 'warn'
  if (l === 'error' || l === 'err') return 'error'
  if (l === 'debug') return 'debug'
  return 'info'
}
</script>

<template>
  <div ref="box" class="logpanel" :style="{ height }" @scroll="onScroll">
    <div v-if="!logs.length" class="empty">暂无日志，任务开始后会在这里实时输出。</div>
    <div v-for="(l, i) in logs" :key="i" class="line">
      <span class="ts">{{ l.ts || '--:--:--' }}</span>
      <span class="lv" :class="levelClass(l.level)">{{ levelClass(l.level) }}</span>
      <span class="msg">{{ l.msg }}</span>
    </div>
  </div>
</template>
