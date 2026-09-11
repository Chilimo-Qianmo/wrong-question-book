import type { LayoutKind, QuestionSource } from '@/api/types'

/** 版面判定 → 中文说明 */
export function layoutKindText(kind: LayoutKind | undefined | null): string {
  switch (kind) {
    case 'digital':
      return '电子版（有文字层）'
    case 'scanned':
      return '扫描版（无文字层）'
    case 'mixed':
      return '混合（按页分流）'
    default:
      return '未知'
  }
}

/** 页面通道 → 中文 */
export function pageKindText(kind: string): string {
  return kind === 'digital' ? '文字层' : 'OCR'
}

/** 题目来源 → 中文徽标文案 */
export function sourceLabel(source: QuestionSource | string): string {
  switch (source) {
    case 'text':
      return '文字层'
    case 'ocr':
      return 'OCR'
    case 'config':
      return '配置'
    case 'mixed':
      return '混合'
    default:
      return String(source || '未知')
  }
}

/** 题目来源 → 徽标配色（绿/橙/蓝/紫） */
export function sourceColor(source: QuestionSource | string): string {
  switch (source) {
    case 'text':
      return 'green'
    case 'ocr':
      return 'orange'
    case 'config':
      return 'blue'
    case 'mixed':
      return 'purple'
    default:
      return 'gray'
  }
}

/** 毫秒 → 可读耗时 */
export function msText(ms: number | undefined | null): string {
  if (!ms || ms <= 0) return '—'
  if (ms < 1000) return Math.round(ms) + ' 毫秒'
  if (ms < 60000) return (ms / 1000).toFixed(1) + ' 秒'
  const m = Math.floor(ms / 60000)
  const s = Math.round((ms % 60000) / 1000)
  return m + ' 分 ' + s + ' 秒'
}

/** 字节 → 可读大小 */
export function sizeText(bytes: number): string {
  if (!bytes || bytes < 0) return '—'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

/** 文件名（兼容 Windows 反斜杠路径） */
export function baseName(p: string): string {
  if (!p) return ''
  const i = Math.max(p.lastIndexOf('\\'), p.lastIndexOf('/'))
  return i >= 0 ? p.slice(i + 1) : p
}

/** 当前时间 HH:mm:ss */
export function nowText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
}
