import type {
  DetectRequest,
  ExcelPeek,
  GenerateRequest,
  HealthInfo,
  ImageFile,
  JobStatus,
  MergeRequest,
  PickRequest,
  QuestionConfig,
  QuestionOut,
  Settings,
  SourceInfo,
} from './types'

export * from './types'

/** 后端不可用时的统一友好提示 */
export const OFFLINE_HINT = '后端未启动或连接失败：请先启动本地服务（一键启动.bat），再回来重试。'

export class ApiError extends Error {
  readonly status: number
  readonly detail: string

  constructor(message: string, status = 0, detail = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** 把任意异常转成可直接展示的中文文案 */
export function errText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message || String(e)
  return String(e)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (e) {
    // 网络层失败：绝大多数情况是后端没起来
    throw new ApiError(OFFLINE_HINT, 0, errText(e))
  }

  if (!res.ok) {
    let detail = ''
    try {
      detail = await res.text()
    } catch {
      detail = ''
    }
    const brief = detail.replace(/\s+/g, ' ').slice(0, 300)
    throw new ApiError('请求失败（HTTP ' + res.status + '）' + (brief ? '：' + brief : ''), res.status, detail)
  }

  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  try {
    return JSON.parse(text) as T
  } catch {
    throw new ApiError('后端返回的不是合法 JSON', res.status, text.slice(0, 300))
  }
}

const get = <T>(path: string): Promise<T> => request<T>(path)
const post = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
const put = <T>(path: string, body: unknown): Promise<T> =>
  request<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

/** 配图统一经 /api/media?path= 读取，前端不直接拼文件路径 */
export function mediaUrl(pathOrUrl: string | null | undefined): string {
  if (!pathOrUrl) return ''
  if (/^https?:\/\//i.test(pathOrUrl) || pathOrUrl.indexOf('/api/') === 0) return pathOrUrl
  return '/api/media?path=' + encodeURIComponent(pathOrUrl)
}

export const api = {
  /* 基础 */
  health: () => get<HealthInfo>('/api/health'),
  getSettings: () => get<Settings>('/api/settings'),
  putSettings: (s: Settings) => put<Settings>('/api/settings', s),
  pick: (req: PickRequest) => post<{ paths: string[] }>('/api/dialog/pick', req),
  openPath: (path: string) => post<{ ok: boolean }>('/api/fs/open', { path }),

  /* 试卷来源 */
  inspectSource: (pdf: string) => post<SourceInfo>('/api/source/inspect', { pdf }),

  /* 任务 */
  jobsDetect: (req: DetectRequest) => post<{ job_id: string }>('/api/jobs/detect', req),
  jobsGenerate: (req: GenerateRequest) => post<{ job_id: string }>('/api/jobs/generate', req),
  jobsMerge: (req: MergeRequest) => post<{ job_id: string }>('/api/jobs/merge', req),
  jobStatus: (id: string) => get<JobStatus>('/api/jobs/' + encodeURIComponent(id)),
  jobCancel: (id: string) => post<{ ok: boolean }>('/api/jobs/' + encodeURIComponent(id) + '/cancel'),
  jobEventsUrl: (id: string) => '/api/jobs/' + encodeURIComponent(id) + '/events',

  /* 题目配置 */
  configFind: (pdf: string | null, outDir: string) =>
    post<{ found: boolean; path: string; config: QuestionConfig }>('/api/config/find', { pdf, out_dir: outDir }),
  configSave: (config: QuestionConfig, exam: string, outDir: string) =>
    post<{ path: string; folder: string }>('/api/config/save', { config, exam, out_dir: outDir }),
  configLoad: (path: string) => post<QuestionConfig>('/api/config/load', { path }),

  /* 配图 */
  imagesList: (imagesRoot: string, qno: number) =>
    post<{ files: ImageFile[] }>('/api/images/list', { images_root: imagesRoot, qno }),
  imagesAssign: (imagesRoot: string, qno: number, paths: string[]) =>
    post<{ files: ImageFile[] }>('/api/images/assign', { images_root: imagesRoot, qno, paths }),
  imagesDelete: (imagesRoot: string, qno: number, names: string[]) =>
    post<{ files: ImageFile[] }>('/api/images/delete', { images_root: imagesRoot, qno, names }),
  imagesAutofill: (pdf: string, imagesRoot: string, questions: QuestionOut[]) =>
    post<{ assigned: Record<string, string[]> }>('/api/images/autofill', {
      pdf,
      images_root: imagesRoot,
      questions,
    }),

  /* 答题表 */
  excelPeek: (path: string) => post<ExcelPeek>('/api/excel/peek', { path }),
}
