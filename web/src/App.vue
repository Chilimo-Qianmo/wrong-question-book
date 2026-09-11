<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import StepNav from '@/components/StepNav.vue'
import { useUiStore } from '@/stores/ui'

// 应用外壳：左侧固定步骤导航 + 顶栏（页面标题 + 后端连接状态）+ 轻提示
const route = useRoute()
const ui = useUiStore()

const pageTitle = computed(() => (route.meta.title as string) || '学生错题集生成器')

onMounted(() => {
  void ui.checkHealth()
})
</script>

<template>
  <div class="layout">
    <StepNav />
    <main class="main">
      <header class="topbar">
        <div class="title">{{ pageTitle }}</div>
        <div class="health" :class="ui.online === null ? '' : ui.online ? 'on' : 'off'">
          <span class="led"></span>
          <span v-if="ui.online === null">正在检测后端…</span>
          <span v-else-if="ui.online">后端已连接<template v-if="ui.version"> · {{ ui.version }}</template></span>
          <span v-else>后端未连接</span>
          <button v-if="ui.online === false" class="btn mini ghost" @click="ui.checkHealth()">重试</button>
        </div>
      </header>

      <RouterView />

      <div class="toast-stack">
        <div v-for="t in ui.toasts" :key="t.id" class="toast" :class="t.type" @click="ui.dismiss(t.id)">
          {{ t.text }}
        </div>
      </div>
    </main>
  </div>
</template>
