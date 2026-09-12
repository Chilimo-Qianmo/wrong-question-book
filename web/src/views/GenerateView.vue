<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, errText } from '@/api'
import { subscribeJob, type JobStream } from '@/api/sse'
import type { GenerateRequest, GenerateResult } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import LogPanel from '@/components/LogPanel.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import { useJobStore } from '@/stores/job'
import { useReviewStore } from '@/stores/review'
import { useSettingsStore } from '@/stores/settings'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'
import { baseName } from '@/utils/format'

// ④ 生成：汇总信息 + POST /api/jobs/generate + SSE 实时进度/日志 + 结果卡片。

const job = useJobStore()
const review = useReviewStore()
const source = useSourceStore()
const settings = useSettingsStore()
const ui = useUiStore()

const stream = ref<JobStream | null>(null)

const task = computed(() => job.tasks.generate)
const result = computed(() => (task.value.result || null) as GenerateResult | null)
const running = computed(() => task.value.running)

/** 生成请求的实际参数（页面展示与提交共用） */
const effective = computed(() => ({
  outDir: source.outDir || settings.settings.out_dir,
  cls: source.className || settings.settings.class_name,
  title: source.examTitle || settings.settings.exam_title,
  imagesRoot: settings.settings.images_root,
  keepImages: settings.settings.keep_images,
}))

onMounted(async () => {
  if (!settings.loaded) await settings.load()
  // v2.3：核对页的「确认核验」只负责进入③配图，生成由用户在本页点「开始生成」触发
})

onUnmounted(() => {
  stream.value?.close()
  stream.value = null
})

function buildRequest(): GenerateRequest {
  return {
    pdf: source.pdf || null,
    excel: source.excel,
    images_root: effective.value.imagesRoot,
    out_dir: effective.value.outDir,
    title: effective.value.title || null,
    cls: effective.value.cls,
    config_path: source.configPath || null,
    // 核对页确认后的题目直接交给后端生成，同时会被落盘为 题目配置.json
    questions: review.questions.length ? review.questions : null,
    keep_images: effective.value.keepImages,
    cleanup: true,
  }
}

async function start() {
  if (!review.total) {
    ui.notify('没有可生成的题目，请先完成「② 题目核对」', 'warn')
    return
  }
  if (!effective.value.outDir) {
    ui.notify('请先填写输出目录', 'warn')
    return
  }
  stream.value?.close()
  job.reset('generate')
  try {
    const r = await api.jobsGenerate(buildRequest())
    job.start('generate', r.job_id)
    job.pushText('generate', '已提交生成任务：' + r.job_id)
    follow(r.job_id)
  } catch (e) {
    job.fail('generate', errText(e))
    ui.notify(errText(e), 'error')
  }
}

function follow(jobId: string) {
  stream.value = subscribeJob(jobId, {
    onLog: (e) => job.pushLog('generate', e),
    onProgress: (p) => job.setProgress('generate', p),
    onResult: (r) => job.setResult('generate', r),
    onError: (e) => job.fail('generate', e.message),
    onDone: (d) => job.finish('generate', d.state),
    onFail: (m) => job.pushText('generate', m, 'warn'),
  })
}

async function cancel() {
  if (!task.value.jobId) return
  try {
    await api.jobCancel(task.value.jobId)
    job.pushText('generate', '已请求取消生成任务', 'warn')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function openFolder(path: string) {
  if (!path) return
  try {
    await api.openPath(path)
    ui.notify('已在资源管理器中打开', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}
</script>

<template>
  <div class="page">
    <section class="card">
      <div class="card-head">
        <h2>待生成信息</h2>
        <RouterLink class="btn mini" to="/review">返回核对</RouterLink>
      </div>

      <div class="kv">
        <div class="item">
          <span class="k">学生数</span>
          <span class="v">{{ source.excelPeek ? source.excelPeek.students : '未选答题表' }}</span>
        </div>
        <div class="item"><span class="k">题数</span><span class="v">{{ review.total }} 题</span></div>
        <div class="item"><span class="k">班级</span><span class="v">{{ effective.cls || '未填写' }}</span></div>
        <div class="item"><span class="k">考试标题</span><span class="v small">{{ effective.title || '未填写' }}</span></div>
        <div class="item">
          <span class="k">输出目录</span>
          <span class="v small" :title="effective.outDir">{{ effective.outDir || '未填写' }}</span>
        </div>
        <div class="item">
          <span class="k">试卷</span>
          <span class="v small">{{ baseName(source.pdf) || (source.configPath ? '使用题目配置' : '—') }}</span>
        </div>
        <div class="item">
          <span class="k">答题表</span>
          <span class="v small">{{ baseName(source.excel) || '未选择' }}</span>
        </div>
        <div class="item">
          <span class="k">保留图片缓存</span>
          <span class="v">{{ effective.keepImages ? '是' : '否' }}</span>
        </div>
      </div>

      <div class="btn-row actions">
        <button class="btn primary lg" :disabled="running || !review.total" @click="start">
          <span v-if="running" class="spinner"></span>
          {{ running ? '正在生成…' : result ? '重新生成' : '开始生成' }}
        </button>
        <button v-if="running" class="btn danger" @click="cancel">取消任务</button>
        <span v-if="!review.total" class="muted">请先在「② 题目核对」完成题目确认。</span>
      </div>
    </section>

    <!-- 进度 -->
    <section v-if="running || task.logs.length" class="card">
      <div class="card-head">
        <h2>生成进度</h2>
        <span class="muted" v-if="task.jobId">任务 {{ task.jobId }}</span>
      </div>
      <ProgressBar :percent="task.percent" :label="running ? '正在生成' : '生成进度'" :stage="task.stage" />
      <div class="muted msg">{{ task.message }}</div>
      <LogPanel :logs="task.logs" />
    </section>

    <!-- 结果 -->
    <section v-if="result" class="card">
      <div class="card-head">
        <h2>生成结果</h2>
        <span class="badge green">已完成</span>
      </div>
      <div class="kv">
        <div class="item"><span class="k">学生数</span><span class="v">{{ result.students }}</span></div>
        <div class="item"><span class="k">文档数</span><span class="v">{{ result.docs }}</span></div>
        <div class="item"><span class="k">已归档</span><span class="v">{{ result.moved }}</span></div>
        <div class="item"><span class="k">未归档</span><span class="v">{{ result.leftover }}</span></div>
      </div>
      <div class="paths">
        <div class="pathrow">
          <span class="k">归档路径</span>
          <span class="mono ellip" :title="result.archive_folder">{{ result.archive_folder || result.out || '—' }}</span>
          <button class="btn mini" @click="openFolder(result.archive_folder || result.out)">打开文件夹</button>
        </div>
        <div v-if="result.config_folder" class="pathrow">
          <span class="k">配置目录</span>
          <span class="mono ellip" :title="result.config_folder">{{ result.config_folder }}</span>
          <button class="btn mini" @click="openFolder(result.config_folder)">打开文件夹</button>
        </div>
      </div>
    </section>

    <!-- 错误 -->
    <section v-if="task.error" class="card">
      <div class="card-head"><h2>生成失败</h2><span class="badge orange">错误</span></div>
      <div class="banner error"><div>{{ task.error }}</div></div>
    </section>

    <EmptyHint
      v-if="!review.total"
      title="还没有可生成的题目"
      text="请先到「① 选择来源」识别试卷，再到「② 题目核对」确认所有题目。"
    />
  </div>
</template>

<style scoped>
.actions {
  margin-top: 14px;
}
.msg {
  margin: 8px 0;
}
.paths {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pathrow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background: var(--c-surface-2);
}
.pathrow .k {
  font-size: 12px;
  color: var(--c-text-3);
  flex: none;
}
.ellip {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
</style>
