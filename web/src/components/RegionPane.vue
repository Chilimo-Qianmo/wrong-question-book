<script setup lang="ts">
import { computed, ref } from 'vue'
import type { RegionOut } from '@/api/types'

// 「原题区域」面板：核对页与配图页共用同一套逻辑 —— 后端按题目区域裁切原卷，
// 鼠标悬停时在图片下方弹出放大镜，点「放大」开弹层看高清大图。
// 两个页面用同一个组件，行为与样式永远一致（改一处两页同步）。

const props = defineProps<{
  qno: number
  regions?: RegionOut[]
  /** 来源试卷 PDF；为空表示这道题没有可显示的原文区域 */
  pdf: string
}>()

const failed = ref(false)
const retry = ref(0)
const regionError = ref('')
const lightbox = ref('')

const primary = computed<RegionOut | undefined>(() =>
  props.regions && props.regions.length ? props.regions[0] : undefined,
)

/** 区域裁剪地址（后端按区域渲染原卷；窗口变宽时浏览器会自动拉伸这张图） */
function regionUrl(dpi = 150): string {
  const reg = primary.value
  if (!props.pdf || !reg || !reg.bbox || reg.bbox.length < 4) return ''
  const q = new URLSearchParams({
    pdf: props.pdf,
    page: String(reg.page || 1),
    x0: String(reg.bbox[0]),
    y0: String(reg.bbox[1]),
    x1: String(reg.bbox[2]),
    y1: String(reg.bbox[3]),
    space: reg.space || 'pdf',
    scale: String(reg.scale || 1),
    dpi: String(dpi),
    r: String(retry.value),
  })
  return '/api/media/region?' + q.toString()
}

const url = computed(() => (failed.value ? '' : regionUrl(150)))

/** 图片加载失败：先自动重试（后端可能正在渲染），仍失败就取回真实原因显示出来 */
async function onError() {
  const n = retry.value + 1
  if (n <= 3) {
    retry.value = n
    return
  }
  let detail = '未知错误'
  try {
    const r = await fetch(regionUrl(150))
    const t = await r.text()
    detail = 'HTTP ' + r.status + ' ' + t.slice(0, 300)
  } catch (e) {
    detail = String(e)
  }
  regionError.value = detail
  failed.value = true
}

/** 手动重试 */
function retryRegion() {
  failed.value = false
  regionError.value = ''
  retry.value += 1
}

/* ===== 悬停放大镜 ===== */
const MAG_W = 320
const MAG_H = 200
const MAG_ZOOM = 2.6
const mag = ref<{
  url: string
  top: number
  left: number
  w: number
  h: number
  rx: number
  ry: number
} | null>(null)

function onMove(ev: MouseEvent) {
  const el = ev.currentTarget as HTMLImageElement
  const r = el.getBoundingClientRect()
  if (!r.width || !r.height) return
  const rx = (ev.clientX - r.left) / r.width
  const ry = (ev.clientY - r.top) / r.height
  if (rx < 0 || rx > 1 || ry < 0 || ry > 1) {
    mag.value = null
    return
  }
  const hi = regionUrl(300)              // 放大镜读高清版（服务端缓存，首次稍慢）
  if (!hi) return
  // 小窗默认贴在图片下方，并做视口边界收敛，避免超出屏幕
  let left = r.left + (r.width - MAG_W) / 2
  left = Math.max(8, Math.min(left, window.innerWidth - MAG_W - 8))
  let top = r.bottom + 8
  if (top + MAG_H > window.innerHeight - 8) top = Math.max(8, r.top - MAG_H - 8)
  mag.value = { url: hi, top, left, w: r.width, h: r.height, rx, ry }
}

function onLeave() {
  mag.value = null
}

function openLightbox() {
  lightbox.value = regionUrl(300)
}

function openInNewTab() {
  if (lightbox.value) window.open(lightbox.value, '_blank')
}
</script>

<template>
  <aside class="cell-region">
    <div class="region-head">
      <span class="badge">第 {{ qno }} 题 · 原题区域</span>
      <span class="spacer"></span>
      <button v-if="primary" class="btn mini ghost" @click="openLightbox">放大</button>
    </div>
    <img
      v-if="primary && pdf && !failed"
      class="region-img"
      :src="url"
      :alt="'第' + qno + '题原题区域'"
      loading="lazy"
      @error="onError"
      @mousemove="onMove"
      @mouseleave="onLeave"
    />
    <div v-else-if="failed" class="empty-region err">
      <div>原题区域加载失败</div>
      <div class="errdetail">{{ regionError || '未知错误' }}</div>
      <button class="btn mini" @click="retryRegion">重试</button>
    </div>
    <div v-else-if="!pdf" class="empty-region">来源不是试卷 PDF，无法显示原题区域</div>
    <div v-else class="empty-region">这道题没有定位到原题区域（题目来自题目配置）</div>

    <!-- 悬停放大镜：贴在图片下方的小窗 -->
    <div
      v-if="mag"
      class="magnifier"
      :style="{ top: mag.top + 'px', left: mag.left + 'px', width: MAG_W + 'px', height: MAG_H + 'px' }"
    >
      <div
        class="magview"
        :style="{
          backgroundImage: 'url(' + mag.url + ')',
          backgroundSize: mag.w * MAG_ZOOM + 'px ' + mag.h * MAG_ZOOM + 'px',
          backgroundPosition:
            -(mag.rx * mag.w * MAG_ZOOM - MAG_W / 2) + 'px ' +
            -(mag.ry * mag.h * MAG_ZOOM - MAG_H / 2) + 'px',
        }"
      ></div>
      <span class="magtip">{{ Math.round(MAG_ZOOM * 100) }}%</span>
    </div>

    <!-- 放大弹层 -->
    <div v-if="lightbox" class="lightbox" @click="lightbox = ''">
      <img :src="lightbox" :alt="'第' + qno + '题原题区域'" />
      <div class="lb-bar">
        <span>第 {{ qno }} 题 · 原题区域</span>
        <span class="spacer"></span>
        <button class="btn mini" @click.stop="openInNewTab">新窗口打开</button>
        <button class="btn mini" @click.stop="lightbox = ''">关闭</button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.cell-region {
  min-width: 0;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.region-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
/* 图片宽度 100%：窗口拉伸时跟着变宽，高度按原图比例自动；不设高度上限 */
.region-img {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 6px;
  border: 1px solid var(--c-border);
  background: #fff;
  cursor: zoom-in;
}
.empty-region {
  padding: 18px 10px;
  text-align: center;
  color: var(--c-text-3);
  font-size: 12px;
  background: var(--c-surface-2);
  border-radius: var(--r-sm);
}
.empty-region.err {
  color: var(--c-red);
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
}
.errdetail {
  color: var(--c-text-3);
  font-size: 11px;
  word-break: break-all;
  max-height: 90px;
  overflow: auto;
  text-align: left;
  width: 100%;
}

/* ===== 放大镜：贴在图片下方的小窗，显示指针附近的放大画面 ===== */
.magnifier {
  position: fixed;
  z-index: 70;
  border: 2px solid #fff;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 10px 28px rgba(17, 22, 28, 0.38);
  background: #fff;
  pointer-events: none;
}
.magview {
  width: 100%;
  height: 100%;
  background-repeat: no-repeat;
}
.magtip {
  position: absolute;
  right: 6px;
  bottom: 4px;
  font-size: 11px;
  color: #fff;
  background: rgba(17, 22, 28, 0.6);
  padding: 1px 6px;
  border-radius: 999px;
}

/* ===== 放大弹层 ===== */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(17, 22, 28, 0.86);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 28px;
  cursor: zoom-out;
}
.lightbox img {
  max-width: 94vw;
  max-height: 82vh;
  background: #fff;
  border-radius: 6px;
}
.lb-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 94vw;
  color: #fff;
  font-size: 13px;
}
</style>
