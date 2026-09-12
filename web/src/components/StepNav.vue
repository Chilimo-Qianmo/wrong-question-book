<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useReviewStore } from '@/stores/review'
import { useUiStore } from '@/stores/ui'

// 左侧固定步骤导航。
// 规则：第②步「题目核对」必须全部勾选完成后，③ 题目配图 / ④ 生成 才解锁
//（与路由守卫一致，双保险；直接改地址栏也会被守卫拦回核对页）。
const route = useRoute()
const review = useReviewStore()
const ui = useUiStore()

const steps = [
  { num: '①', label: '选择来源', path: '/' },
  { num: '②', label: '题目核对', path: '/review' },
  { num: '③', label: '题目配图', path: '/images', needVerified: true },
  { num: '④', label: '生成', path: '/generate', needVerified: true },
  { num: '⑤', label: '合并', path: '/merge' },
  { num: '⑥', label: '设置', path: '/settings' },
]

function locked(s: { needVerified?: boolean }): boolean {
  return !!s.needVerified && !review.allVerified
}

function onStep(s: { path: string; needVerified?: boolean }, ev: MouseEvent) {
  if (!locked(s)) return
  ev.preventDefault()
  ui.notify(
    review.total > 0
      ? '请先完成第②步：逐题勾选「已核对」，全部勾选后点「确认核验」'
      : '请先识别试卷并完成第②步核对',
    'warn',
  )
}
</script>

<template>
  <nav class="stepnav">
    <div class="brand">
      学生错题集生成器
      <small>错题集 · v2 前端</small>
    </div>
    <RouterLink
      v-for="s in steps"
      :key="s.path"
      :to="s.path"
      class="step"
      :class="{ active: route.path === s.path, locked: locked(s) }"
      :title="locked(s) ? '第②步「题目核对」全部勾选后才能进入' : ''"
      @click="onStep(s, $event)"
    >
      <span class="num">{{ s.num }}</span>
      <span>{{ s.label }}</span>
      <span v-if="locked(s)" class="lock">锁</span>
    </RouterLink>
    <div class="navfoot">识别 → 核对 → 配图 → 生成<br />全程本地运行，不外传数据</div>
  </nav>
</template>
