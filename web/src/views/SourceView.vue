<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, errText } from '@/api'
import type { QuestionConfig } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import PickerButton from '@/components/PickerButton.vue'
import { useJobStore } from '@/stores/job'
import { useReviewStore } from '@/stores/review'
import { useSettingsStore } from '@/stores/settings'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'
import { baseName, layoutKindText, pageKindText } from '@/utils/format'

// ① 选择来源：试卷 PDF / 题目配置 JSON（互斥）、答题表 Excel、输出参数、开始识别。

const source = useSourceStore()
const settings = useSettingsStore()
const review = useReviewStore()
const job = useJobStore()
const ui = useUiStore()
const router = useRouter()

const config = ref<QuestionConfig | null>(null)
const configError = ref('')
const loadingConfig = ref(false)

onMounted(async () => {
  if (!settings.loaded) {
    const ok = await settings.load()
    if (ok) source.applySettingsDefaults(settings.settings)
  }
  if (source.configPath) void loadConfigPreview()
})

/** 来源判定徽标配色 */
const kindColor = computed(() => {
  const k = source.sourceInfo?.kind
  if (k === 'digital') return 'green'
  if (k === 'mixed') return 'purple'
  return 'orange'
})

function onPdf(paths: string[]) {
  if (!paths.length) return
  source.pickPdf(paths[0])
  config.value = null
  configError.value = ''
}

function onConfig(paths: string[]) {
  if (!paths.length) return
  source.pickConfig(paths[0])
  void loadConfigPreview()
}

function onExcel(paths: string[]) {
  if (!paths.length) return
  source.pickExcel(paths[0])
}

function onOutDir(paths: string[]) {
  if (!paths.length) return
  source.outDir = paths[0]
  source.persist()
}

/** 预览配置 JSON 内容（POST /api/config/load） */
async function loadConfigPreview() {
  if (!source.configPath) return
  loadingConfig.value = true
  configError.value = ''
  try {
    config.value = await api.configLoad(source.configPath)
  } catch (e) {
    config.value = null
    configError.value = errText(e)
  } finally {
    loadingConfig.value = false
  }
}

const configSummary = computed(() => {
  const c = config.value
  if (!c) return null
  return {
    version: c.schema_version,
    stems: Object.keys(c.stems || {}).length,
    options: Object.keys(c.options || {}).length,
    tables: Object.keys(c.tables || {}).length,
    figures: Object.keys(c.figures || {}).length,
    match: c.match || '（未标注）',
    exam: c.source_exam || '（未标注）',
  }
})

function clearSource() {
  source.pickConfig('')
  source.pdf = ''
  source.configPath = ''
  source.sourceInfo = null
  source.inspectError = ''
  config.value = null
  source.persist()
}

/** 开始识别：POST /api/jobs/detect → 跳转 ② 题目核对 */
async function startDetect() {
  if (!source.hasSource) {
    ui.notify('请先选择试卷 PDF 或题目配置 JSON', 'warn')
    return
  }
  if (!source.outDir) ui.notify('还没有填输出目录，生成时会再问一次', 'warn')
  const id = await source.startDetect()
  if (!id) return
  job.start('detect', id)
  review.reset()
  router.push('/review')
}
</script>

<template>
  <div class="page">
    <!-- 试卷来源 -->
    <section class="card">
      <div class="card-head">
        <h2>
          试卷来源
          <span class="sub">试卷 PDF 与题目配置 JSON 二选一</span>
        </h2>
      </div>

      <div class="btn-row">
        <PickerButton kind="pdf" label="选择试卷 PDF" variant="primary" :initialdir="source.outDir" @picked="onPdf" />
        <PickerButton kind="config" label="选择题目配置 JSON" :initialdir="source.outDir" @picked="onConfig" />
        <button v-if="source.hasSource" class="btn ghost" @click="clearSource">清空选择</button>
      </div>

      <div v-if="source.hasSource" class="chosen">
        <span class="chip" :title="source.pdf || source.configPath">
          {{ source.pdf ? '试卷 PDF' : '题目配置' }}：{{ baseName(source.pdf || source.configPath) }}
        </span>
      </div>

      <!-- 来源体检卡片 -->
      <div v-if="source.pdf" class="inspect">
        <div v-if="source.inspecting" class="empty"><span class="spinner"></span> 正在体检试卷来源…</div>
        <div v-else-if="source.inspectError" class="banner error">
          <div>
            <strong>来源体检失败：</strong>{{ source.inspectError }}
            <button class="btn mini" @click="source.inspect()">重试</button>
          </div>
        </div>
        <template v-else-if="source.sourceInfo">
          <div class="row">
            <span class="badge" :class="kindColor">{{ layoutKindText(source.sourceInfo.kind) }}</span>
            <span class="muted">{{ source.sourceInfo.name || baseName(source.sourceInfo.path) }}</span>
          </div>
          <div class="kv">
            <div class="item">
              <span class="k">页数</span><span class="v">{{ source.sourceInfo.pages }}</span>
            </div>
            <div class="item">
              <span class="k">总文字层字符数</span><span class="v">{{ source.sourceInfo.total_chars }}</span>
            </div>
            <div class="item">
              <span class="k">含文字层</span><span class="v">{{ source.sourceInfo.has_text_layer ? '是' : '否' }}</span>
            </div>
            <div class="item">
              <span class="k">识别通道</span>
              <span class="v">{{ source.sourceInfo.kind === 'scanned' ? 'OCR' : '文字层优先，扫描页回退 OCR' }}</span>
            </div>
          </div>

          <div v-if="(source.sourceInfo.notes || []).length" class="notes">
            <div v-for="(n, i) in source.sourceInfo.notes" :key="i" class="banner info">{{ n }}</div>
          </div>

          <div v-if="(source.sourceInfo.page_infos || []).length" class="tbl-wrap pagetable">
            <table class="tbl">
              <thead>
                <tr>
                  <th>页码</th>
                  <th>文字层字符数</th>
                  <th>通道</th>
                  <th>表格数</th>
                  <th>图片数</th>
                  <th>页面尺寸</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="p in source.sourceInfo.page_infos" :key="p.page">
                  <td class="num">{{ p.page }}</td>
                  <td class="num">{{ p.text_chars }}</td>
                  <td>
                    <span class="badge" :class="p.kind === 'digital' ? 'green' : 'orange'">
                      {{ pageKindText(p.kind) }}
                    </span>
                  </td>
                  <td class="num">{{ p.tables }}</td>
                  <td class="num">{{ p.images }}</td>
                  <td class="num muted">{{ Math.round(p.width) }} × {{ Math.round(p.height) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </div>

      <!-- 配置 JSON 预览 -->
      <div v-if="source.configPath" class="inspect">
        <div v-if="loadingConfig" class="empty"><span class="spinner"></span> 正在读取配置…</div>
        <div v-else-if="configError" class="banner error">
          <div><strong>配置读取失败：</strong>{{ configError }}</div>
        </div>
        <template v-else-if="configSummary">
          <div class="row">
            <span class="badge blue">配置</span>
            <span class="muted">schema_version {{ configSummary.version }}</span>
          </div>
          <div class="kv">
            <div class="item"><span class="k">题干条目</span><span class="v">{{ configSummary.stems }}</span></div>
            <div class="item"><span class="k">选项条目</span><span class="v">{{ configSummary.options }}</span></div>
            <div class="item"><span class="k">表格规格</span><span class="v">{{ configSummary.tables }}</span></div>
            <div class="item"><span class="k">配图条目</span><span class="v">{{ configSummary.figures }}</span></div>
            <div class="item"><span class="k">来源标注</span><span class="v small">{{ configSummary.exam }}</span></div>
          </div>
          <div class="banner info">
            使用配置 JSON 时不会再解析 PDF；配置里缺项的题目会按后端规则回退。
          </div>
        </template>
      </div>
    </section>

    <!-- 答题情况 Excel -->
    <section class="card">
      <div class="card-head">
        <h2>
          答题情况表
          <span class="sub">用于统计每位学生的错题（可留空，留空则生成全题版）</span>
        </h2>
      </div>

      <div class="btn-row">
        <PickerButton kind="excel" label="选择答题情况 Excel" :initialdir="source.outDir" @picked="onExcel" />
        <button v-if="source.excel" class="btn ghost" @click="source.peekExcel()">重新解析</button>
      </div>

      <div v-if="source.excel" class="chosen">
        <span class="chip" :title="source.excel">Excel：{{ baseName(source.excel) }}</span>
      </div>

      <div v-if="source.peeking" class="empty"><span class="spinner"></span> 正在解析答题表…</div>
      <div v-else-if="source.excelError" class="banner error">
        <div><strong>答题表解析失败：</strong>{{ source.excelError }}</div>
      </div>
      <template v-else-if="source.excelPeek">
        <div class="kv">
          <div class="item"><span class="k">学生数</span><span class="v">{{ source.excelPeek.students }}</span></div>
          <div class="item"><span class="k">工作表</span><span class="v small">{{ source.excelPeek.sheet }}</span></div>
          <div class="item"><span class="k">推断班级</span><span class="v">{{ source.excelPeek.class_name || '未推断出' }}</span></div>
          <div class="item"><span class="k">姓名列</span><span class="v">第 {{ source.excelPeek.name_column }} 列</span></div>
          <div class="item">
            <span class="k">题号列（{{ (source.excelPeek.question_columns || []).length }}）</span>
            <span class="v small">{{ (source.excelPeek.question_columns || []).join(', ') || '—' }}</span>
          </div>
        </div>

        <div v-if="(source.excelPeek.missing_columns || []).length" class="banner warn">
          <div>
            <strong>缺失列告警：</strong>第 {{ (source.excelPeek.missing_columns || []).join('、') }} 列没有找到对应题号，
            这些题会被当作「全班都做错」处理，请确认答题表是否完整。
          </div>
        </div>
        <div v-for="(n, i) in source.excelPeek.notes || []" :key="i" class="banner info">{{ n }}</div>
      </template>
    </section>

    <!-- 输出设置 -->
    <section class="card">
      <div class="card-head"><h2>输出设置</h2></div>
      <div class="grid-2">
        <div class="field">
          <label class="flabel">输出目录</label>
          <div class="row">
            <input v-model="source.outDir" type="text" placeholder="例如 D:\错题集" @change="source.persist()" />
            <PickerButton kind="dir" label="浏览…" @picked="onOutDir" />
          </div>
        </div>
        <div class="field">
          <label class="flabel">班级</label>
          <input v-model="source.className" type="text" placeholder="例如 14班" @change="source.persist()" />
        </div>
        <div class="field">
          <label class="flabel">考试标题</label>
          <input v-model="source.examTitle" type="text" placeholder="例如 2026 届高三摸底考试" @change="source.persist()" />
        </div>
        <div class="field">
          <label class="flabel">识别选项</label>
          <label class="check">
            <input v-model="source.useCache" type="checkbox" @change="source.persist()" />
            复用识别缓存（换卷后会自动失效）
          </label>
        </div>
      </div>
    </section>

    <div class="footer-actions">
      <button class="btn primary lg" :disabled="!source.canDetect" @click="startDetect">开始识别</button>
      <span class="muted">识别完成后会自动跳到「② 题目核对」。</span>
    </div>

    <EmptyHint
      v-if="!source.hasSource"
      title="先选一份试卷"
      text="支持电子版（有文字层，秒级识别）与扫描版（OCR）两种试卷，选完会立刻做一次来源体检。"
    />
  </div>
</template>

<style scoped>
.chosen {
  margin-top: 10px;
}
.inspect {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--c-border);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.pagetable {
  max-height: 260px;
}
.notes {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.footer-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 4px 2px;
}
</style>
