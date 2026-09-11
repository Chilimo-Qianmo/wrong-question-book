import { api, errText } from './index'
import type { DoneEvent, ErrorEvent, JobStatus, LogEvent, ProgressEvent } from './types'

// 任务事件订阅（SSE）：log / progress / result / error / done 五类事件。
// 契约要求「同一个任务 id 只能订阅一次」，因此：
//   1. 本页面会话内记住已订阅过的 id，重复订阅自动降级为状态轮询；
//   2. 连接中断时主动 close（禁止 EventSource 自动重连），改用 GET /api/jobs/{id} 拿终态。

export interface JobStreamHandlers {
  onLog?: (e: LogEvent) => void
  onProgress?: (e: ProgressEvent) => void
  onResult?: (payload: Record<string, unknown>) => void
  onError?: (e: ErrorEvent) => void
  onDone?: (e: DoneEvent) => void
  /** 连接层异常（不是任务失败），例如后端没启动 */
  onFail?: (message: string) => void
}

export interface JobStream {
  readonly closed: boolean
  close(): void
}

const subscribed = new Set<string>()

function parseJson<T>(raw: unknown): T | null {
  if (typeof raw !== 'string' || !raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function subscribeJob(jobId: string, handlers: JobStreamHandlers, pollMs = 1200): JobStream {
  let closed = false
  let es: EventSource | null = null
  let timer: number | null = null

  const stopTransport = () => {
    if (es) {
      es.onerror = null
      es.close()
      es = null
    }
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
  }

  const close = () => {
    if (closed) return
    closed = true
    stopTransport()
  }

  // 兜底通道：轮询任务状态，直到终态
  const poll = () => {
    if (closed) return
    const tick = async () => {
      if (closed) return
      let st: JobStatus
      try {
        st = await api.jobStatus(jobId)
      } catch (e) {
        close()
        handlers.onFail?.('无法获取任务状态：' + errText(e))
        return
      }
      if (closed) return
      if (st.state === 'running') {
        handlers.onProgress?.({ stage: '', done: 0, total: 0, percent: st.percent, msg: st.message })
        timer = window.setTimeout(tick, pollMs)
        return
      }
      if (st.result) handlers.onResult?.(st.result)
      if (st.state === 'error') handlers.onError?.({ message: st.error || '任务执行失败' })
      close()
      handlers.onDone?.({ state: st.state })
    }
    timer = window.setTimeout(tick, 500)
  }

  if (subscribed.has(jobId)) {
    handlers.onFail?.('该任务已订阅过事件流，改用状态查询继续跟踪…')
    poll()
    return {
      get closed() {
        return closed
      },
      close,
    }
  }
  subscribed.add(jobId)

  try {
    es = new EventSource(api.jobEventsUrl(jobId))
  } catch (e) {
    handlers.onFail?.('无法建立事件流连接：' + errText(e))
    poll()
    return {
      get closed() {
        return closed
      },
      close,
    }
  }

  es.addEventListener('log', (ev: Event) => {
    const d = parseJson<LogEvent>((ev as MessageEvent).data)
    if (d) handlers.onLog?.(d)
  })

  es.addEventListener('progress', (ev: Event) => {
    const d = parseJson<ProgressEvent>((ev as MessageEvent).data)
    if (d) handlers.onProgress?.(d)
  })

  es.addEventListener('result', (ev: Event) => {
    const d = parseJson<Record<string, unknown>>((ev as MessageEvent).data)
    if (d) handlers.onResult?.(d)
  })

  es.addEventListener('error', (ev: Event) => {
    const data = (ev as MessageEvent).data
    // 带 data 的是后端主动推送的 error 事件；不带 data 的是连接层错误
    if (typeof data === 'string' && data) {
      handlers.onError?.(parseJson<ErrorEvent>(data) ?? { message: '任务执行出错' })
      return
    }
    if (closed) return
    handlers.onFail?.('事件流连接中断，正在改用状态查询继续跟踪…')
    stopTransport()
    poll()
  })

  es.addEventListener('done', (ev: Event) => {
    const d = parseJson<DoneEvent>((ev as MessageEvent).data) ?? { state: 'done' as const }
    close()
    handlers.onDone?.(d)
  })

  return {
    get closed() {
      return closed
    },
    close,
  }
}
