// 与 docs/API.md + app/models.py 一一对应的类型定义。
// 字段名严格保持 snake_case（契约冻结，不要改）。

/** 版面类型：digital=有文字层 / scanned=整页图片 / mixed=混合（按页分流） */
export type LayoutKind = 'digital' | 'scanned' | 'mixed'
export type PageKind = 'digital' | 'scanned'

/** 题目来源标注 */
export type QuestionSource = 'text' | 'ocr' | 'config' | 'mixed' | 'manual'

/** 任务状态 */
export type JobState = 'running' | 'done' | 'error' | 'cancelled'

/** 原生对话框类型 */
export type PickKind = 'pdf' | 'excel' | 'dir' | 'images' | 'config' | 'any'

export type LogLevel = 'info' | 'warn' | 'error' | 'debug'

export interface PageInfo {
  page: number
  width: number
  height: number
  text_chars: number
  kind: PageKind
  tables: number
  images: number
}

export interface SourceInfo {
  path: string
  name: string
  pages: number
  kind: LayoutKind
  page_infos: PageInfo[]
  total_chars: number
  has_text_layer: boolean
  notes: string[]
}

/** 被规则剔除、未能进入题干/选项的文本（绝不静默丢弃） */
export interface DroppedText {
  text: string
  page: number
  bbox: number[]
  reason: string
}

export interface FigureRef {
  id: string
  page: number
  bbox: number[]
  path: string | null
  url: string | null
  auto: boolean
  width: number
  height: number
}

export interface TableSpec {
  columns: string[]
  rows: string[][]
  as_answer: boolean
}

export interface TableRef {
  id: string
  page: number
  bbox: number[]
  cells: string[][] | null
  source: 'structured' | 'ruled' | 'manual'
  as_answer: boolean
  spec: TableSpec | null
  image_url: string | null
}

/** 题目在原始试卷上的区域（核对页右侧「原题区域」用） */
export interface RegionOut {
  page: number
  bbox: number[]
  space: 'pdf' | 'render'
  scale: number
}

export interface QuestionOut {
  qno: number
  page: number
  stem: string
  regions: RegionOut[]
  options: Record<string, string>
  source: QuestionSource
  conf: number
  warnings: string[]
  dropped: DroppedText[]
  figures: FigureRef[]
  tables: TableRef[]
  verified: boolean
}

export interface Gap {
  expected: number
  found: number
  message: string
}

export interface DetectPayload {
  source: SourceInfo | null
  questions: QuestionOut[]
  gaps: Gap[]
  declared_count: number | null
  keyword: string
  elapsed_ms: number
}

export interface QuestionConfig {
  schema_version: number
  match: string
  source_exam: string
  stems: Record<string, string>
  options: Record<string, Record<string, string>>
  tables: Record<string, TableSpec>
  figures: Record<string, FigureRef[]>
}

export interface DetectRequest {
  pdf?: string | null
  config_path?: string | null
  out_dir?: string
  use_cache?: boolean
  prefer_text_layer?: boolean
  scale?: number
}

export interface Settings {
  out_dir: string
  images_root: string
  class_name: string
  exam_title: string
  keep_images: boolean
  auto_open_after_generate: boolean
  font_name: string
  body_size: number
  line_spacing: number
  page_margin_cm: number
}

export interface GenerateRequest {
  pdf?: string | null
  excel?: string
  images_root?: string
  out_dir?: string
  title?: string | null
  cls?: string
  config_path?: string | null
  config?: QuestionConfig | null
  /** 核对页确认后的题目（后端优先使用） */
  questions?: QuestionOut[] | null
  keep_images?: boolean
  cleanup?: boolean
}

export interface GenerateResult {
  students: number
  docs: number
  out: string
  archive_folder: string
  config_folder: string
  moved: number
  leftover: number
}

export interface MergeRequest {
  folders: string[]
  out_dir: string
  deduplicate: boolean
  copy_single: boolean
}

export interface MergeResult {
  merged: number
  copied: number
  outs: string[]
  logs: string[]
}

export interface JobStatus {
  id: string
  kind: string
  state: JobState
  percent: number
  message: string
  result: Record<string, unknown> | null
  error: string
  started_at: number
  finished_at: number
}

export interface PickRequest {
  kind: PickKind
  title?: string
  multi?: boolean
  initialdir?: string
}

export interface ExcelPeek {
  path: string
  sheet: string
  students: number
  question_columns: number[]
  missing_columns: number[]
  class_name: string
  name_column: number
  notes: string[]
}

export interface ImageFile {
  name: string
  path: string
  url: string
  size: number
}

export interface HealthInfo {
  ok: boolean
  version: string
  engine: { pdfplumber: boolean; rapidocr: boolean; opencv: boolean }
}

/* ===== SSE 事件负载 ===== */
export interface LogEvent {
  ts: string
  level: LogLevel | string
  msg: string
}
export interface ProgressEvent {
  stage: string
  done: number
  total: number
  percent: number
  msg: string
}
export interface ErrorEvent {
  message: string
  traceback?: string
}
export interface DoneEvent {
  state: 'done' | 'error' | 'cancelled'
}
