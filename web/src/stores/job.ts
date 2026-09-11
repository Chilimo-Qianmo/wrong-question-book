import { ref } from 'vue'
import { defineStore } from 'pinia'
import type { JobState, LogEvent, ProgressEvent } from '@/api/types'

// 任务状态（识别 / 生成 / 合并）：进度、日志、结果、错误。
// 事件流本身由组件持有（卸载时关闭），这里只保存可展示的状态。

export type TaskKind = 'detect' | 'generate' | 'merge'

export interface TaskState {
  kind: TaskKind
  jobId: string
  state: JobState | 'idle'
  percent: number
  stage: string
  message: string
  logs: LogEvent[]
  result: Record<string, unknown> | null
  error: string
  running: boolean
  startedAt: number
}

const MAX_LOGS = 800

function blank(kind: TaskKind): TaskState {
  return {
    kind,
    jobId: '',
    state: 'idle',
    percent: 0,
    stage: '',
    message: '',
    logs: [],
    result: null,
    error: '',
    running: false,
    startedAt: 0,
  }
}

export const useJobStore = defineStore('job', () => {
  const tasks = ref<Record<TaskKind, TaskState>>({
    detect: blank('detect'),
    generate: blank('generate'),
    merge: blank('merge'),
  })

  function start(kind: TaskKind, jobId: string) {
    tasks.value[kind] = { ...blank(kind), jobId, state: 'running', running: true, startedAt: Date.now() }
  }

  function reset(kind: TaskKind) {
    tasks.value[kind] = blank(kind)
  }

  function pushLog(kind: TaskKind, e: LogEvent) {
    const t = tasks.value[kind]
    t.logs.push(e)
    if (t.logs.length > MAX_LOGS) t.logs.splice(0, t.logs.length - MAX_LOGS)
  }

  function pushText(kind: TaskKind, msg: string, level: string = 'info') {
    const d = new Date()
    const p = (n: number) => String(n).padStart(2, '0')
    pushLog(kind, { ts: p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds()), level, msg })
  }

  function setProgress(kind: TaskKind, e: ProgressEvent) {
    const t = tasks.value[kind]
    if (typeof e.percent === 'number' && isFinite(e.percent)) t.percent = Math.max(0, Math.min(100, e.percent))
    if (e.msg) t.message = e.msg
    if (e.stage) t.stage = e.stage
  }

  function setResult(kind: TaskKind, result: Record<string, unknown> | null) {
    tasks.value[kind].result = result
  }

  function fail(kind: TaskKind, message: string) {
    const t = tasks.value[kind]
    t.error = message
    t.state = 'error'
    t.running = false
  }

  function finish(kind: TaskKind, state: JobState) {
    const t = tasks.value[kind]
    t.state = state
    t.running = false
    if (state === 'done') t.percent = 100
    if (state === 'cancelled') t.message = t.message || '任务已取消'
  }

  return { tasks, start, reset, pushLog, pushText, setProgress, setResult, fail, finish }
})
