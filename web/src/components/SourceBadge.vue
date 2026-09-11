<script setup lang="ts">
import { computed } from 'vue'
import type { QuestionSource } from '@/api/types'
import { sourceColor, sourceLabel } from '@/utils/format'

// 题目来源徽标：文字层=绿 / OCR=橙 / 配置=蓝 / 混合=紫
const props = defineProps<{ source: QuestionSource | string }>()

const text = computed(() => sourceLabel(props.source))
const color = computed(() => sourceColor(props.source))
</script>

<template>
  <span class="badge" :class="color">{{ text }}</span>
</template>
