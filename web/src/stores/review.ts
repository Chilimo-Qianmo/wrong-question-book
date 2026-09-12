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

  /** 下一个可用题号（识别结果里的最大题号 + 1，至少 1） */
  function nextQno(): number {
    const nums = questions.value.map((q) => Number(q.qno) || 0)
    return (nums.length ? Math.max(...nums) : 0) + 1
  }

  /** 新增一道自编题目：插到指定位置（默认末尾） */
  function addQuestion(afterIndex = -1): QuestionOut {
    const q: QuestionOut = normalize({
      qno: nextQno(),
      page: 0,
      stem: '',
      regions: [],
      options: { A: '', B: '', C: '', D: '' },
      source: 'manual',
      conf: 1,
      warnings: ['自编题目：请填写题干与选项'],
      dropped: [],
      figures: [],
      tables: [],
      verified: false,
    } as unknown as QuestionOut)
    const list = questions.value.slice()
    if (afterIndex >= 0 && afterIndex < list.length) list.splice(afterIndex + 1, 0, q)
    else list.push(q)
    questions.value = list
    return q
  }

  /** 删除一道题 */
  function removeQuestion(qno: number) {
    questions.value = questions.value.filter((q) => q.qno !== qno)
  }

  /** 修改题号（避免与已有题号重复） */
  function setQno(oldQno: number, newQno: number): boolean {
    if (!newQno || newQno < 1) return false
    if (questions.value.some((q) => q.qno === newQno && q.qno !== oldQno)) return false
    const q = questions.value.find((item) => item.qno === oldQno)
    if (!q) return false
    q.qno = newQno
    questions.value = questions.value.slice().sort((a, b) => a.qno - b.qno)
    return true
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
    nextQno,
    addQuestion,
    removeQuestion,
    setQno,
    absorbDropped,
    reset,
  }
})
