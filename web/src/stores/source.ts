import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, errText } from '@/api'
import type { ExcelPeek, Settings, SourceInfo } from '@/api/types'
import { useUiStore } from './ui'

// ① 选择来源页的全局状态：来源文件、体检结果、答题表、输出参数。

const LS_KEY = 'wtt.source.v1'

interface Persisted {
  pdf: string
  configPath: string
  excel: string
  outDir: string
  className: string
  examTitle: string
  useCache: boolean
}

function loadPersisted(): Partial<Persisted> {
  try {
    const raw = window.localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as Partial<Persisted>) : {}
  } catch {
    return {}
  }
}

export const useSourceStore = defineStore('source', () => {
  const saved = loadPersisted()

  const pdf = ref(saved.pdf || '')
  const configPath = ref(saved.configPath || '')
  const excel = ref(saved.excel || '')
  const outDir = ref(saved.outDir || '')
  const className = ref(saved.className || '')
  const examTitle = ref(saved.examTitle || '')
  const useCache = ref(saved.useCache !== false)

  const sourceInfo = ref<SourceInfo | null>(null)
  const inspecting = ref(false)
  const inspectError = ref('')

  const excelPeek = ref<ExcelPeek | null>(null)
  const peeking = ref(false)
  const excelError = ref('')

  /** 最近一次识别任务 id，供核对页订阅 */
  const detectJobId = ref('')

  const hasSource = computed(() => !!(pdf.value || configPath.value))
  const canDetect = computed(() => hasSource.value && !inspecting.value)

  function persist() {
    try {
      const data: Persisted = {
        pdf: pdf.value,
        configPath: configPath.value,
        excel: excel.value,
        outDir: outDir.value,
        className: className.value,
        examTitle: examTitle.value,
        useCache: useCache.value,
      }
      window.localStorage.setItem(LS_KEY, JSON.stringify(data))
    } catch {
      /* 忽略：隐私模式下 localStorage 可能不可用 */
    }
  }

  /** 选定试卷 PDF：与配置 JSON 互斥，并立刻做来源体检 */
  function pickPdf(path: string) {
    pdf.value = path
    configPath.value = ''
    sourceInfo.value = null
    inspectError.value = ''
    persist()
    void inspect()
  }

  /** 选定题目配置 JSON：与 PDF 互斥 */
  function pickConfig(path: string) {
    configPath.value = path
    pdf.value = ''
    sourceInfo.value = null
    inspectError.value = ''
    persist()
  }

  function pickExcel(path: string) {
    excel.value = path
    persist()
    void peekExcel()
  }

  /** 来源体检：POST /api/source/inspect */
  async function inspect() {
    if (!pdf.value) return
    inspecting.value = true
    inspectError.value = ''
    try {
      sourceInfo.value = await api.inspectSource(pdf.value)
    } catch (e) {
      sourceInfo.value = null
      inspectError.value = errText(e)
    } finally {
      inspecting.value = false
    }
  }

  /** 答题表预览：POST /api/excel/peek */
  async function peekExcel() {
    if (!excel.value) return
    peeking.value = true
    excelError.value = ''
    try {
      excelPeek.value = await api.excelPeek(excel.value)
      // 后端推断出班级时，若用户还没填班级则自动带上
      if (!className.value && excelPeek.value.class_name) {
        className.value = excelPeek.value.class_name
        persist()
      }
    } catch (e) {
      excelPeek.value = null
      excelError.value = errText(e)
    } finally {
      peeking.value = false
    }
  }

  /** 后端 settings 里的默认值，仅在本地为空时套用 */
  function applySettingsDefaults(s: Settings) {
    if (!outDir.value && s.out_dir) outDir.value = s.out_dir
    if (!className.value && s.class_name) className.value = s.class_name
    if (!examTitle.value && s.exam_title) examTitle.value = s.exam_title
    persist()
  }

  /** 组装识别请求入参 */
  function detectRequest() {
    return {
      pdf: pdf.value || null,
      config_path: configPath.value || null,
      out_dir: outDir.value,
      use_cache: useCache.value,
      prefer_text_layer: true,
      scale: 3.0,
    }
  }

  /** 开始识别：POST /api/jobs/detect，返回任务 id */
  async function startDetect(): Promise<string> {
    const ui = useUiStore()
    if (!hasSource.value) {
      ui.notify('请先选择试卷 PDF 或题目配置 JSON', 'warn')
      return ''
    }
    try {
      const r = await api.jobsDetect(detectRequest())
      detectJobId.value = r.job_id
      return r.job_id
    } catch (e) {
      ui.notify('启动识别失败：' + errText(e), 'error')
      return ''
    }
  }

  function reset() {
    pdf.value = ''
    configPath.value = ''
    excel.value = ''
    sourceInfo.value = null
    excelPeek.value = null
    inspectError.value = ''
    excelError.value = ''
    detectJobId.value = ''
    persist()
  }

  return {
    pdf,
    configPath,
    excel,
    outDir,
    className,
    examTitle,
    useCache,
    sourceInfo,
    inspecting,
    inspectError,
    excelPeek,
    peeking,
    excelError,
    detectJobId,
    hasSource,
    canDetect,
    persist,
    pickPdf,
    pickConfig,
    pickExcel,
    inspect,
    peekExcel,
    applySettingsDefaults,
    detectRequest,
    startDetect,
    reset,
  }
})
