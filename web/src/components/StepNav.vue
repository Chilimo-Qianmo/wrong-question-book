<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useReviewStore } from '@/stores/review'
import { useSourceStore } from '@/stores/source'

// 左侧固定步骤导航
const route = useRoute()
const source = useSourceStore()
const review = useReviewStore()

const steps = [
  { num: '①', label: '选择来源', path: '/' },
  { num: '②', label: '题目核对', path: '/review' },
  { num: '③', label: '题目配图', path: '/images' },
  { num: '④', label: '生成', path: '/generate' },
  { num: '⑤', label: '合并', path: '/merge' },
  { num: '⑥', label: '设置', path: '/settings' },
]

/** 步骤右侧的小圆点：有数据时提示「这一步已经有内容了」 */
function done(path: string): boolean {
  if (path === '/') return source.hasSource
  if (path === '/review') return review.total > 0
  if (path === '/generate') return review.total > 0
  return false
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
      :class="{ active: route.path === s.path }"
    >
      <span class="num">{{ s.num }}</span>
      <span>{{ s.label }}</span>
      <span v-if="done(s.path) && route.path !== s.path" class="dot" title="已有内容"></span>
    </RouterLink>
    <div class="navfoot">识别 → 核对 → 配图 → 生成<br />全程本地运行，不外传数据</div>
  </nav>
</template>
