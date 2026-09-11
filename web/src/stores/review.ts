import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { DetectPayload, Gap, QuestionOut, SourceInfo } from '@/api/types'

// ② 题目核对页的全局状态：识别结果 + 逐题勾选情况。

export const useReviewStore = defineStore('review', () => {
  const questions = ref<QuestionOut[]>([])
  const gaps = ref<Gap[]>([])
  const sourceInfo = ref<SourceInfo | null>(null)
  const declaredCount = ref<number | null>(null)
  const keyword = ref('')
  const elapsedMs = ref(0)
  const error = ref('')
  /** 核对完成并确认生成（④ 页据此自动开始生成） */
  const confirmed = ref(false)

  const total = computed(() => questions.value.length)
  const verifiedCount = computed(() => questions.value.filter((q) => q.verified).length)
  const allVerified = computed(() => total.value > 0 && verifiedCount.value === total.value)
  const issueCount = computed(
    () => questions.value.filter((q) => (q.warnings || []).length > 0 || (q.dropped || []).length > 0).length,
  )

  /** 补齐后端可能省略的字段，模板里就不必到处判空 */
  function normalize(q: QuestionOut): QuestionOut {
    return {
      qno: q.qno,
      page: q.page || 0,
      stem: q.stem || '',
      regions: q.regions || [],
      options: q.options || {},
      source: q.source || 'ocr',
      conf: typeof q.conf === 'number' ? q.conf : 1,
      warnings: q.warnings || [],
      dropped: q.dropped || [],
      figures: q.figures || [],
      tables: q.tables || [],
      verified: !!q.verified,
    }
  }

  /** 接收 DetectPayload（SSE result 或 GET /api/jobs/{id} 的 result） */
  function applyPayload(p: DetectPayload | null | undefined) {
    if (!p) return
    questions.value = (p.questions || []).map(normalize)
    gaps.value = p.gaps || []
    sourceInfo.value = p.source || null
    declaredCount.value = typeof p.declared_count === 'number' ? p.declared_count : null
    keyword.value = p.keyword || ''
    elapsedMs.value = p.elapsed_ms || 0
    error.value = ''
  }

  function setAllVerified(v: boolean) {
    questions.value.forEach((q) => {
      q.verified = v
    })
  }

  /** 第一道未核对题的下标，找不到返回 -1 */
  function firstUnverifiedIndex(): number {
    return questions.value.findIndex((q) => !q.verified)
  }

  /** 把「已忽略文本」并入题干（核对页一键还原） */
  function absorbDropped(qno: number, index: number) {
    const q = questions.value.find((item) => item.qno === qno)
    if (!q) return
    const d = q.dropped[index]
    if (!d) return
    const text = (d.text || '').trim()
    if (text) {
      q.stem = q.stem ? q.stem.replace(/\s+$/, '') + '\n' + text : text
    }
    q.dropped.splice(index, 1)
  }

  function reset() {
    questions.value = []
    gaps.value = []
    sourceInfo.value = null
    declaredCount.value = null
    keyword.value = ''
    elapsedMs.value = 0
    error.value = ''
    confirmed.value = false
  }

  return {
    questions,
    gaps,
    sourceInfo,
    declaredCount,
    keyword,
    elapsedMs,
    error,
    confirmed,
    total,
    verifiedCount,
    allVerified,
    issueCount,
    applyPayload,
    setAllVerified,
    firstUnverifiedIndex,
    absorbDropped,
    reset,
  }
})
