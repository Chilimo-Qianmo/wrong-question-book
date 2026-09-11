<script setup lang="ts">
// 统一的空状态 / 友好提示块（后端未启动、暂无数据等）
withDefaults(defineProps<{ title: string; text?: string; tone?: 'info' | 'warn' | 'error' }>(), {
  text: '',
  tone: 'info',
})
</script>

<template>
  <div class="empty">
    <div class="big">{{ title }}</div>
    <div v-if="text">{{ text }}</div>
    <div v-if="$slots.default" class="slot"><slot /></div>
  </div>
</template>

<style scoped>
.slot {
  margin-top: 12px;
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
}
</style>
