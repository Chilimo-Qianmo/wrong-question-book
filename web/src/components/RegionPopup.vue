<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { RegionOut } from '@/api/types'
import { useRegionImage } from '@/utils/region'

// 配图页的「原题切割画面」悬浮预览：
// 鼠标移到某题的选项框（拖放区）上时，在该题**上方**浮出一块画面显示原卷对应区域的裁剪图。
// 纯展示、不拦截鼠标（pointer-events:none），鼠标移开即收起，不会影响拖拽配图。

export interface PopAnchor {
  qno: number
  /** 吸附的矩形（拖放区的视口坐标） */
  top: number
  bottom: number
  left: number
  width: number
  /** true = 优先浮在题目上方；false = 直接落在下方 */
  up: boolean
}

const props = defineProps<{
  anchor: PopAnchor
  regions?: RegionOut[]
  pdf: string
}>()

const { primary, src, failed, detail, onError } = useRegionImage(
  () => props.pdf,
  () => props.regions,
)

const el = ref<HTMLElement | null>(null)
/** 上方确实放不下时（题目贴着屏幕顶部）才翻到下方 */
const flip = ref(false)

const upward = computed(() => props.anchor.up && !flip.value)

const style = computed(() => {
  const a = props.anchor
  const base: Record<string, string> = {
    left: a.left + 'px',
    width: a.width + 'px',
  }
  if (upward.value) base.bottom = window.innerHeight - a.top + 10 + 'px'
  else base.top = a.bottom + 10 + 'px'
  return base
})

/** 渲染后量一次真实高度：上方放不下就翻到题目下面 */
function adjust() {
  const node = el.value
  if (!node || !props.anchor.up || flip.value) return
  if (node.getBoundingClientRect().top < 8) flip.value = true
}

onMounted(() => nextTick(adjust))
watch(
  () => props.anchor,
  () => {
    flip.value = false
    void nextTick(adjust)
  },
)
</script>

<template>
  <div ref="el" class="region-pop" :style="style">
    <div class="pop-head">
      <span class="badge">第 {{ anchor.qno }} 题 · 原题切割画面</span>
      <span class="spacer"></span>
      <span class="hint">{{ upward ? '浮在题目前方上方 · 移开即收起' : '移开鼠标即收起' }}</span>
    </div>
    <img
      v-if="primary && pdf && !failed"
      class="pop-img"
      :src="src"
      :alt="'第' + anchor.qno + '题原题区域'"
      @error="onError"
      @load="adjust"
    />
    <div v-else-if="failed" class="pop-empty err">
      原题区域加载失败：{{ detail || '未知错误' }}
    </div>
    <div v-else-if="!pdf" class="pop-empty">来源不是试卷 PDF，无法显示原题区域</div>
    <div v-else class="pop-empty">这道题没有定位到原题区域（题目来自题目配置）</div>
  </div>
</template>

<style scoped>
.region-pop {
  position: fixed;
  z-index: 65;
  background: var(--c-surface);
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-lg);
  box-shadow: 0 16px 38px rgba(17, 22, 28, 0.28);
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  pointer-events: none;
  animation: popin 0.12s ease-out;
}
@keyframes popin {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.pop-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hint {
  font-size: 11px;
  color: var(--c-text-3);
}
.pop-img {
  display: block;
  width: 100%;
  height: auto;
  max-height: 46vh;
  object-fit: contain;
  background: #fff;
  border: 1px solid var(--c-border);
  border-radius: 6px;
}
.pop-empty {
  padding: 22px 10px;
  text-align: center;
  font-size: 12px;
  color: var(--c-text-3);
  background: var(--c-surface-2);
  border-radius: var(--r-sm);
}
.pop-empty.err {
  color: var(--c-red);
}
</style>
