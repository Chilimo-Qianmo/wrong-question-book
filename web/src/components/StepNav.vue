<script setup lang="ts">
import { useRoute } from 'vue-router'

// 左侧固定步骤导航（仅做导航，不显示任何状态指示）
const route = useRoute()

const steps = [
  { num: '①', label: '选择来源', path: '/' },
  { num: '②', label: '题目核对', path: '/review' },
  { num: '③', label: '题目配图', path: '/images' },
  { num: '④', label: '生成', path: '/generate' },
  { num: '⑤', label: '合并', path: '/merge' },
  { num: '⑥', label: '设置', path: '/settings' },
]
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
    </RouterLink>
    <div class="navfoot">识别 → 核对 → 配图 → 生成<br />全程本地运行，不外传数据</div>
  </nav>
</template>
