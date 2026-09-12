<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '@/api'
import { subscribeJob, type JobStream } from '@/api/sse'
import type { DetectPayload, RegionOut } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import QuestionCard from '@/components/QuestionCard.vue'
import { useJobStore } from '@/stores/job'
import { useReviewStore } from '@/stores/review'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'
import { baseName, layoutKindText, msText } from '@/utils/format'

// ② 题目核对：**每道题一行**，左侧 2/3 是题目编辑卡片，右侧 1/3 紧挨着显示
//    该题在原始试卷上的区域，两边自动对齐；右侧图片随窗口宽度自适应缩放。

const route = useRoute()
const router = useRouter()
const job = useJobStore()
const review = useReviewStore()
const source = useSourceStore()
const ui = useUiStore()

const stream = ref<JobStream | null>(null)
const flashIndex = ref(-1)
const currentIndex = ref(0)
const failed = ref<Record<number, boolean>>({})
const retry = ref<Record<number, number>>({})
const regionError = ref<Record<number, string>>({})

const jobId = computed(() => source.detectJobId || String(route.query.job || ''))
const task = computed(() => job.tasks.detect)
const running = computed(() => task.value.running)

const info = computed(() => review.sourceInfo || source.sourceInfo)
const channelText = computed(() => (info.value ? layoutKindText(info.value.kind) : '—'))
const unverified = computed(() => review.total - review.verifiedCount)
const pdfPath = computed(() => info.value?.path || source.pdf || '')

/** 题目区域裁剪地址（后端按区域渲染原卷；窗口变宽时浏览器会自动拉伸这张图） */
function regionUrl(reg: RegionOut | undefined): string {
  const p = pdfPath.value
  if (!p || !reg || !reg.bbox || reg.bbox.length < 4) return ''
  const q = new URLSearchParams({
    pdf: p,
    page: String(reg.page || 1),
    x0: String(reg.bbox[0]),
    y0: String(reg.bbox[1]),
    x1: String(reg.bbox[2]),
    y1: String(reg.bbox[3]),
    space: reg.space || 'pdf',
    scale: String(reg.scale || 1),
    dpi: '150',                       // 与后端预热用的 DPI 一致，直接命中缓存
    r: String(retry.value[reg.page] || 0),
  })
  return '/api/media/region?' + q.toString()
}

/** 图片加载失败：先自动重试（后端可能正在渲染），仍失败就取回真实原因显示出来 */
async function onRegionError(qno: number, page: number, url: string) {
  const n = (retry.value[page] || 0) + 1
  if (n <= 3) {
    retry.value = { ...retry.value, [page]: n }
    return
  }
  let detail = '未知错误'
  try {
    const r = await fetch(url)
    const t = await r.text()
    detail = 'HTTP ' + r.status + ' ' + t.slice(0, 300)
  } catch (e) {
    detail = String(e)
  }
  regionError.value = { ...regionError.value, [qno]: detail }
  failed.value = { ...failed.value, [qno]: true }
}

/** 手动重试某题的原题区域 */
function retryRegion(qno: number, page: number) {
  const f = { ...failed.value }
  delete f[qno]
  failed.value = f
  const e = { ...regionError.value }
  delete e[qno]
  regionError.value = e
  retry.value = { ...retry.value, [page]: (retry.value[page] || 0) + 1 }
}

function primaryRegion(q: { regions?: RegionOut[] }): RegionOut | undefined {
  return q.regions && q.regions.length ? q.regions[0] : undefined
}

/* ===== 放大：弹层预览（与配图页看图一致）；另加鼠标悬停放大镜 ===== */
const lightbox = ref<{ url: string; title: string } | null>(null)
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

/** 高分辨率版本（放大镜/弹层用，服务端渲染后缓存，首次稍慢） */
function regionUrlHi(reg: RegionOut | undefined, dpi = 300): string {
  const u = regionUrl(reg)
  return u ? u.replace('dpi=150', 'dpi=' + dpi) : ''
}

function openLightbox(q: { qno: number; regions?: RegionOut[] }) {
  const u = regionUrlHi(primaryRegion(q))
  if (!u) {
    ui.notify('这道题没有可放大的原题区域', 'warn')
    return
  }
  lightbox.value = { url: u, title: '第 ' + q.qno + ' 题 · 原题区域' }
}

/** 鼠标在图片上移动 → 在图片下方显示一个放大镜小窗 */
function onRegionMove(q: { qno: number; regions?: RegionOut[] }, ev: MouseEvent) {
  const el = ev.currentTarget as HTMLImageElement
  const r = el.getBoundingClientRect()
  if (!r.width || !r.height) return
  const rx = (ev.clientX - r.left) / r.width
  const ry = (ev.clientY - r.top) / r.height
  if (rx < 0 || rx > 1 || ry < 0 || ry > 1) {
    mag.value = null
    return
  }
  const url = regionUrlHi(primaryRegion(q))
  if (!url) return
  // 小窗默认贴在图片下方，并做视口边界收敛，避免超出屏幕
  let left = r.left + (r.width - MAG_W) / 2
  left = Math.max(8, Math.min(left, window.innerWidth - MAG_W - 8))
  let top = r.bottom + 8
  if (top + MAG_H > window.innerHeight - 8) top = Math.max(8, r.top - MAG_H - 8)
  mag.value = { url, top, left, w: r.width, h: r.height, rx, ry }
}

function onRegionLeave() {
  mag.value = null
}

function openInNewTab(url: string) {
  if (url) window.open(url, '_blank')
}

function setCurrent(i: number) {
  currentIndex.value = i
}

onMounted(async () => {
  if (!jobId.value) return
  try {
    const st = await api.jobStatus(jobId.value)
    if (st.result) review.applyPayload(st.result as unknown as DetectPayload)
    if (st.state === 'done') {
      job.finish('detect', 'done')
      return
    }
    if (st.state === 'error') {
      job.fail('detect', st.error || '识别失败')
      return
    }
    if (st.state === 'cancelled') {
      job.finish('detect', 'cancelled')
      return
    }
  } catch (e) {
    job.pushText('detect', errText(e), 'error')
  }
  follow()
})

watch(
  () => review.questions.length,
  (n) => {
    if (!n) return
    const bad = review.questions.findIndex((q) => (q.warnings?.length || 0) > 0 || q.conf < 0.9)
    currentIndex.value = bad >= 0 ? bad : 0
  },
)

function follow() {
  if (!jobId.value) return
  stream.value = subscribeJob(jobId.value, {
    onLog: (e) => job.pushLog('detect', e),
    onProgress: (p) => job.setProgress('detect', p),
    onResult: (r) => {
      job.setResult('detect', r)
      review.applyPayload(r as unknown as DetectPayload)
    },
    onError: (e) => {
      job.fail('detect', e.message)
      review.error = e.message
    },
    onDone: (d) => job.finish('detect', d.state),
    onFail: (m) => job.pushText('detect', m, 'warn'),
  })
}

onUnmounted(() => {
  stream.value?.close()
  stream.value = null
})

function scrollToQuestion(index: number) {
  const q = review.questions[index]
  if (!q) return
  setCurrent(index)
  const el = document.getElementById('qrow-' + q.qno)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  flashIndex.value = index
  window.setTimeout(() => {
    flashIndex.value = -1
  }, 1800)
}

function verifyAll() {
  review.setAllVerified(true)
  ui.notify('已把 ' + review.total + ' 题标记为已核对', 'success')
}

function unverifyAll() {
  review.setAllVerified(false)
}

/** 确认核验：全部勾选后进入下一步「③ 题目配图」（v2.3 起不再直接生成） */
function confirmVerify() {
  if (!review.total) {
    ui.notify('还没有题目，请先识别试卷或手动添加题目', 'warn')
    return
  }
  if (!review.allVerified) {
    const i = review.firstUnverifiedIndex()
    scrollToQuestion(i)
    const qno = review.questions[i] ? review.questions[i].qno : '-'
    ui.notify('还有 ' + unverified.value + ' 题未勾选「已核对」，已定位到第 ' + qno + ' 题', 'warn')
    return
  }
  review.confirmed = true
  ui.notify('核对完成，下一步去「③ 题目配图」', 'success')
  router.push('/images')
}

/** 新增一道自编题目（可自定义题干与选项） */
function addQuestion() {
  const q = review.addQuestion()
  ui.notify('已新增第 ' + q.qno + ' 题，可直接编辑题干与选项', 'success')
  void nextTick(() => {
    const el = document.getElementById('qrow-' + q.qno)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

async function cancelDetect() {
  if (!task.value.jobId) return
  try {
    await api.jobCancel(task.value.jobId)
    job.pushText('detect', '已请求取消识别任务', 'warn')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}
</script>

<template>
  <div class="page">
    <!-- 缺口告警横幅 -->
    <div v-if="review.gaps.length" class="banner warn gaps">
      <div>
        <strong>识别缺口：</strong>
        <span v-for="(g, i) in review.gaps" :key="i" class="gapitem">
          第 {{ g.expected }} 题未识别到，请检查{{ g.message ? '（' + g.message + '）' : '' }}
        </span>
      </div>
    </div>

    <!-- 识别概览 -->
    <section class="card">
      <div class="card-head">
        <h2>识别概览</h2>
        <div class="row">
          <button v-if="running" class="btn mini danger" @click="cancelDetect">取消识别</button>
          <RouterLink class="btn mini" to="/">重新选择来源</RouterLink>
        </div>
      </div>

      <div class="kv">
        <div class="item"><span class="k">识别题数</span><span class="v">{{ review.total }} 题</span></div>
        <div class="item">
          <span class="k">声明题数</span>
          <span class="v">{{ review.declaredCount === null ? '—' : review.declaredCount + ' 题' }}</span>
        </div>
        <div class="item"><span class="k">用时</span><span class="v">{{ msText(review.elapsedMs) }}</span></div>
        <div class="item"><span class="k">来源通道</span><span class="v">{{ channelText }}</span></div>
        <div class="item">
          <span class="k">来源文件</span>
          <span class="v small" :title="info?.path || ''">{{ info?.name || baseName(source.pdf) || '—' }}</span>
        </div>
        <div class="item"><span class="k">需关注题目</span><span class="v">{{ review.issueCount }} 题</span></div>
      </div>

      <div v-if="running" class="running">
        <ProgressBar :percent="task.percent" label="正在识别" :stage="task.stage" />
        <div class="muted">{{ task.message || '正在解析试卷…' }}</div>
      </div>

      <div v-if="task.error" class="banner error">
        <div><strong>识别失败：</strong>{{ task.error }}</div>
      </div>
      <div v-else-if="task.state === 'cancelled'" class="banner warn">识别任务已取消。</div>
    </section>

    <!-- 每道题一行：左 2/3 编辑区，右 1/3 原题区域（自动对齐） -->
    <div v-if="review.total" class="review-grid">
      <template v-for="(q, i) in review.questions" :key="q.qno">
        <div
          :id="'qrow-' + q.qno"
          class="cell-card"
          :class="{ active: i === currentIndex, flashing: flashIndex === i }"
          @click="setCurrent(i)"
        >
          <QuestionCard :q="q" :index="i" :flashing="flashIndex === i" />
        </div>

        <aside class="cell-region">
          <div class="region-head">
            <span class="badge">第 {{ q.qno }} 题 · 原题区域</span>
            <button
              v-if="primaryRegion(q)"
              class="btn mini ghost"
              @click.stop="openLightbox(q)"
            >放大</button>
          </div>
          <img
            v-if="primaryRegion(q) && pdfPath && !failed[q.qno]"
            class="region-img"
            :src="regionUrl(primaryRegion(q))"
            :alt="'第' + q.qno + '题原题区域'"
            loading="lazy"
            @error="onRegionError(q.qno, primaryRegion(q)!.page, regionUrl(primaryRegion(q)))"
            @mousemove="onRegionMove(q, $event)"
            @mouseleave="onRegionLeave"
          />
          <div v-else-if="failed[q.qno]" class="empty-region err">
            <div>原题区域加载失败</div>
            <div class="errdetail">{{ regionError[q.qno] || '未知错误' }}</div>
            <button class="btn mini" @click="retryRegion(q.qno, primaryRegion(q)!.page)">重试</button>
          </div>
          <div v-else-if="!pdfPath" class="empty-region">来源不是试卷 PDF，无法显示原题区域</div>
          <div v-else class="empty-region">这道题没有定位到原题区域（题目来自题目配置）</div>
        </aside>
      </template>
    </div>

    <!-- 放大镜小窗：跟随鼠标显示指针附近的放大画面 -->
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
    <div v-if="lightbox" class="lightbox" @click="lightbox = null">
      <img :src="lightbox.url" :alt="lightbox.title" />
      <div class="lb-bar">
        <span>{{ lightbox.title }}</span>
        <span class="spacer"></span>
        <button class="btn mini" @click.stop="openInNewTab(lightbox.url)">新窗口打开</button>
        <button class="btn mini" @click.stop="lightbox = null">关闭</button>
      </div>
    </div>

    <EmptyHint
      v-if="!review.total && !running"
      title="还没有识别结果"
      text="请到「① 选择来源」选好试卷后点击「开始识别」，识别完成后题目会出现在这里。"
    >
      <button class="btn primary" @click="router.push('/')">去选择来源</button>
      <button class="btn" @click="addQuestion">＋ 手动添加题目</button>
    </EmptyHint>
  </div>

  <!-- 底部操作栏 -->
  <div v-if="review.total" class="actionbar">
    <button class="btn primary" @click="addQuestion">＋ 添加题目</button>
    <button class="btn" @click="verifyAll">一键全部核验</button>
    <button class="btn ghost" @click="unverifyAll">全部取消勾选</button>
    <span class="spacer"></span>
    <span class="counter" :class="{ ok: review.allVerified }">
      已核对 {{ review.verifiedCount }} / {{ review.total }} 题
    </span>
    <button class="btn primary lg" @click="confirmVerify">确认核验</button>
  </div>
</template>

<style scoped>
.gaps {
  font-size: 14px;
}
.gapitem {
  display: inline-block;
  margin-right: 14px;
}
.running {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.counter {
  font-size: 14px;
  color: var(--c-text-2);
  font-weight: 500;
}
.counter.ok {
  color: var(--c-green);
}

/* ===== 每题一行：左 2/3 + 右 1/3，天然对齐 ===== */
.review-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;   /* 题目编辑区与原题区域各占一半 */
  gap: 14px 16px;
  align-items: start;
}
.cell-card {
  min-width: 0;
  border-radius: var(--r-lg);
  transition: box-shadow 0.15s ease;
  cursor: default;
}
.cell-card.active {
  box-shadow: 0 0 0 2px var(--c-primary-soft);
}
.cell-card.flashing {
  animation: cardflash 0.45s ease-in-out 3;
}
@keyframes cardflash {
  0%, 100% { background: transparent; }
  50% { background: var(--c-primary-soft); }
}

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

/* ===== 放大弹层（与配图页看图一致） ===== */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 60;
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

/* 窄屏（如窗口很小时）自动改为上下布局，避免右侧被挤没 */
@media (max-width: 1100px) {
  .review-grid {
    grid-template-columns: 1fr;
  }
}
</style>
