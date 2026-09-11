<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, errText } from '@/api'
import { subscribeJob, type JobStream } from '@/api/sse'
import type { DetectPayload } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import QuestionCard from '@/components/QuestionCard.vue'
import { useJobStore } from '@/stores/job'
import { useReviewStore } from '@/stores/review'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'
import { baseName, layoutKindText, msText } from '@/utils/format'

// ② 题目核对：识别概览 + 缺口告警 + 逐题卡片 + 底部核对操作栏。

const route = useRoute()
const router = useRouter()
const job = useJobStore()
const review = useReviewStore()
const source = useSourceStore()
const ui = useUiStore()

const stream = ref<JobStream | null>(null)
const flashIndex = ref(-1)

/** 任务 id：来自 ① 页，或 URL 上的 ?job=（刷新后仍可继续跟踪） */
const jobId = computed(() => source.detectJobId || String(route.query.job || ''))
const task = computed(() => job.tasks.detect)
const running = computed(() => task.value.running)

const info = computed(() => review.sourceInfo || source.sourceInfo)
const channelText = computed(() => (info.value ? layoutKindText(info.value.kind) : '—'))
const unverified = computed(() => review.total - review.verifiedCount)

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

    <!-- 题目卡片列表 -->
    <QuestionCard
      v-for="(q, i) in review.questions"
      :key="q.qno"
      :q="q"
      :index="i"
      :flashing="flashIndex === i"
    />

    <EmptyHint
      v-if="!review.total && !running"
      title="还没有识别结果"
      text="请到「① 选择来源」选好试卷后点击「开始识别」，识别完成后题目会出现在这里。"
    >
      <button class="btn primary" @click="router.push('/')">去选择来源</button>
    </EmptyHint>
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
</style>
