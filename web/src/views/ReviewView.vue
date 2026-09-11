<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
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

// ② 题目核对：两栏布局
//   左栏（占 2/3）：识别概览 + 逐题卡片（原有全部功能）
//   右栏（占 1/3）：当前题在原始试卷上的区域，方便逐字对照

const route = useRoute()
const router = useRouter()
const job = useJobStore()
const review = useReviewStore()
const source = useSourceStore()
const ui = useUiStore()

const stream = ref<JobStream | null>(null)
const flashIndex = ref(-1)
const currentIndex = ref(0)
const zoom = ref(1)
const failed = ref<Record<string, boolean>>({})

/** 任务 id：来自 ① 页，或 URL 上的 ?job=（刷新后仍可继续跟踪） */
const jobId = computed(() => source.detectJobId || String(route.query.job || ''))
const task = computed(() => job.tasks.detect)
const running = computed(() => task.value.running)

const info = computed(() => review.sourceInfo || source.sourceInfo)
const channelText = computed(() => (info.value ? layoutKindText(info.value.kind) : '—'))
const unverified = computed(() => review.total - review.verifiedCount)
const current = computed(() => review.questions[currentIndex.value] || null)
const currentRegions = computed<RegionOut[]>(() => current.value?.regions || [])
const pdfPath = computed(() => info.value?.path || source.pdf || '')

/** 题目区域裁剪地址（后端按区域渲染原卷） */
function regionUrl(reg: RegionOut): string {
  const p = pdfPath.value
  if (!p || !reg.bbox || reg.bbox.length < 4) return ''
  const q = new URLSearchParams({
    pdf: p,
    page: String(reg.page || 1),
    x0: String(reg.bbox[0]),
    y0: String(reg.bbox[1]),
    x1: String(reg.bbox[2]),
    y1: String(reg.bbox[3]),
    space: reg.space || 'pdf',
    scale: String(reg.scale || 1),
    dpi: '170',
  })
  return '/api/media/region?' + q.toString()
}

function setCurrent(i: number) {
  currentIndex.value = i
  zoom.value = 1
  failed.value = {}
}

function openBig(url: string) {
  if (url) window.open(url, '_blank')
}

onMounted(async () => {
  if (!jobId.value) return
  // 先取一次任务状态：跳转瞬间可能已经错过了 SSE 事件
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
    // 后端不可用：不白屏，只提示，并继续尝试订阅事件流
    job.pushText('detect', errText(e), 'error')
  }
  follow()
})

// 题目出来后，默认定位到第一道「需关注」的题，便于优先核对
watch(
  () => review.questions.length,
  (n) => {
    if (!n) return
    const bad = review.questions.findIndex((q) => (q.warnings?.length || 0) > 0 || q.conf < 0.9)
    currentIndex.value = bad >= 0 ? bad : 0
  },
)

/** 订阅识别任务事件流 */
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
  // 组件卸载时关闭事件流
  stream.value?.close()
  stream.value = null
})

function scrollToQuestion(index: number) {
  const q = review.questions[index]
  if (!q) return
  setCurrent(index)
  const el = document.getElementById('q-' + q.qno)
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

/** 确认核验并生成：未勾选时定位到第一道未核对题 */
function confirmGenerate() {
  if (!review.total) {
    ui.notify('还没有题目可以生成', 'warn')
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
  router.push('/generate')
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

    <div class="split">
      <!-- ============ 左栏：原有全部功能（2/3） ============ -->
      <div class="col-left">
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

        <div
          v-for="(q, i) in review.questions"
          :key="q.qno"
          class="qwrap"
          :class="{ active: i === currentIndex }"
          @click="setCurrent(i)"
        >
          <QuestionCard :q="q" :index="i" :flashing="flashIndex === i" />
        </div>

        <EmptyHint
          v-if="!review.total && !running"
          title="还没有识别结果"
          text="请到「① 选择来源」选好试卷后点击「开始识别」，识别完成后题目会出现在这里。"
        >
          <button class="btn primary" @click="router.push('/')">去选择来源</button>
        </EmptyHint>
      </div>

      <!-- ============ 右栏：当前题的原题区域（1/3） ============ -->
      <aside class="col-right">
        <section class="card region-card">
          <div class="card-head">
            <h2>
              <template v-if="current">第 {{ current.qno }} 题 · 原题区域</template>
              <template v-else>原题区域</template>
            </h2>
          </div>

          <template v-if="current">
            <div class="toolbar">
              <button class="btn mini" @click="zoom = Math.max(0.5, zoom - 0.25)" title="缩小">－</button>
              <span class="zoomv">{{ Math.round(zoom * 100) }}%</span>
              <button class="btn mini" @click="zoom = Math.min(3, zoom + 0.25)" title="放大">＋</button>
              <button class="btn mini" @click="zoom = 1">适应宽度</button>
              <span class="spacer"></span>
              <button
                v-if="currentRegions.length"
                class="btn mini ghost"
                @click="openBig(regionUrl(currentRegions[0]))"
              >在新窗口打开</button>
            </div>

            <div v-if="!currentRegions.length" class="empty-region">
              这道题没有原题区域（题目来自题目配置，或未在试卷中定位到）。
              <br />可在左侧直接核对题干与选项。
            </div>
            <div v-else-if="!pdfPath" class="empty-region">
              当前来源不是试卷 PDF，无法显示原题区域。
            </div>
            <div v-else class="region-scroll">
              <template v-for="(reg, ri) in currentRegions" :key="ri">
                <img
                  v-if="!failed[ri]"
                  class="region-img"
                  :src="regionUrl(reg)"
                  :style="{ width: zoom * 100 + '%' }"
                  alt="原题区域"
                  @error="failed[ri] = true"
                />
                <div v-else class="empty-region">第 {{ reg.page }} 页区域加载失败，请重试。</div>
              </template>
            </div>

            <div class="region-foot">
              <span v-if="currentRegions.length" class="muted small">
                第 {{ currentRegions[0].page }} 页 · 直接裁自原卷
              </span>
              <span class="spacer"></span>
              <span class="badge" :class="current.conf >= 0.9 ? 'ok' : 'warn'">
                置信度 {{ Math.round(current.conf * 100) }}%
              </span>
            </div>
          </template>

          <EmptyHint
            v-else
            title="尚未选择题目"
            text="点击左侧任意题目卡片，这里会显示该题在原始试卷上的位置，方便逐字对照。"
          />
        </section>
      </aside>
    </div>
  </div>

  <!-- 底部操作栏 -->
  <div v-if="review.total" class="actionbar">
    <button class="btn" @click="verifyAll">一键全部核验</button>
    <button class="btn ghost" @click="unverifyAll">全部取消勾选</button>
    <span class="spacer"></span>
    <span class="counter" :class="{ ok: review.allVerified }">
      已核对 {{ review.verifiedCount }} / {{ review.total }} 题
    </span>
    <button class="btn primary lg" @click="confirmGenerate">确认核验并生成</button>
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

/* ===== 两栏布局：左 2/3，右 1/3 ===== */
.split {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.col-left {
  flex: 2 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.col-right {
  flex: 1 1 0;
  min-width: 300px;
  position: sticky;
  top: 12px;
}
.qwrap {
  border-radius: var(--r-lg);
  transition: box-shadow 0.15s ease;
}
.qwrap.active {
  box-shadow: 0 0 0 2px var(--c-primary-soft);
}

/* ===== 右栏：原题区域 ===== */
.region-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
}
.zoomv {
  font-size: 12px;
  color: var(--c-text-3);
  min-width: 40px;
  text-align: center;
}
.region-scroll {
  max-height: 62vh;
  overflow: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background: var(--c-surface-2);
  padding: 6px;
}
.region-img {
  display: block;
  max-width: none;
  border-radius: 4px;
  background: #fff;
}
.empty-region {
  padding: 22px 12px;
  text-align: center;
  color: var(--c-text-3);
  font-size: 13px;
  line-height: 1.7;
  background: var(--c-surface-2);
  border-radius: var(--r-md);
}
.region-foot {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 窄屏（如 1366 或窗口很小时）自动改为上下布局，避免右栏被挤没 */
@media (max-width: 1100px) {
  .split {
    flex-direction: column;
  }
  .col-right {
    position: static;
    width: 100%;
    min-width: 0;
  }
}
</style>
