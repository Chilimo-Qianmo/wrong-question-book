import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { RegionOut } from '@/api/types'

// 原题区域的取图逻辑（地址拼装 / 自动重试 / 真实错误回显）：
// 核对页的内嵌面板、配图页的悬浮预览共用这一份，行为永远一致。

export interface RegionImageApi {
  /** 这道题在试卷上的第一个区域 */
  primary: ComputedRef<RegionOut | undefined>
  /** 按 DPI 取图地址（dpi 越大越清晰，服务端有缓存） */
  url: (dpi?: number) => string
  /** 默认预览地址（失败后为空串） */
  src: ComputedRef<string>
  failed: Ref<boolean>
  detail: Ref<string>
  onError: () => Promise<void>
  retryNow: () => void
}

export function useRegionImage(
  pdf: () => string,
  regions: () => RegionOut[] | undefined,
): RegionImageApi {
  const failed = ref(false)
  const retry = ref(0)
  const detail = ref('')

  const primary = computed<RegionOut | undefined>(() => {
    const rs = regions()
    return rs && rs.length ? rs[0] : undefined
  })

  /** 区域裁剪地址（后端按区域渲染原卷；窗口变宽时浏览器会自动拉伸这张图） */
  function url(dpi = 150): string {
    const reg = primary.value
    const p = pdf()
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
      dpi: String(dpi),
      r: String(retry.value),
    })
    return '/api/media/region?' + q.toString()
  }

  const src = computed(() => (failed.value ? '' : url(150)))

  /** 图片加载失败：先自动重试（后端可能正在渲染），仍失败就取回真实原因 */
  async function onError() {
    const n = retry.value + 1
    if (n <= 3) {
      retry.value = n
      return
    }
    let d = '未知错误'
    try {
      const r = await fetch(url(150))
      d = 'HTTP ' + r.status + ' ' + (await r.text()).slice(0, 300)
    } catch (e) {
      d = String(e)
    }
    detail.value = d
    failed.value = true
  }

  function retryNow() {
    failed.value = false
    detail.value = ''
    retry.value += 1
  }

  return { primary, url, src, failed, detail, onError, retryNow }
}
