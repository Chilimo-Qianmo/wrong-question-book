<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, errText, mediaUrl } from '@/api'
import type { ImageFile } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import PickerButton from '@/components/PickerButton.vue'
import { useReviewStore } from '@/stores/review'
import { useSettingsStore } from '@/stores/settings'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'
import { sizeText } from '@/utils/format'

// ③ 题目配图（可视化版）
//   · 题目缩略图墙：一眼看出每道题有没有图、有几张、长什么样
//   · 点选题目 → 下方显示该题图片的大缩略图，可直接删除
//   · 支持「从 PDF 自动抽取配图」一键归属

const settings = useSettingsStore()
const review = useReviewStore()
const source = useSourceStore()
const ui = useUiStore()

const imagesRoot = ref('')
const selected = ref(0)
const files = ref<ImageFile[]>([])
const counts = ref<Record<number, number>>({})
const thumbs = ref<Record<number, string>>({})
const loading = ref(false)
const error = ref('')
const preview = ref<ImageFile | null>(null)
const autofillRunning = ref(false)
const assigned = ref<Record<string, string[]>>({})

/** 有识别结果就用识别到的题号，否则给 1~20 的兜底网格 */
const questionNumbers = computed(() => {
  const qs = review.questions.map((q) => q.qno).sort((a, b) => a - b)
  if (qs.length) return qs
  return Array.from({ length: 20 }, (_, i) => i + 1)
})
const hasQuestions = computed(() => review.questions.length > 0)

const assignedRows = computed(() =>
  Object.keys(assigned.value)
    .map((k) => ({ qno: Number(k), count: (assigned.value[k] || []).length }))
    .sort((a, b) => a.qno - b.qno),
)
const totalImages = computed(() =>
  Object.values(counts.value).reduce((s, n) => s + n, 0),
)

onMounted(async () => {
  if (!settings.loaded) await settings.load()
  imagesRoot.value = settings.settings.images_root || ''
  if (questionNumbers.value.length) selected.value = questionNumbers.value[0]
  await refreshAll()
})

watch(imagesRoot, (v) => {
  settings.patch({ images_root: v })
  void refreshAll()
})

/** 扫描所有题目：图片数量 + 首图缩略图 + 当前题图片列表 */
async function refreshAll() {
  if (!imagesRoot.value) {
    error.value = '还没有设置「图片根目录」，请先到「⑥ 设置」里填写，或点下方「浏览…」。'
    files.value = []
    counts.value = {}
    thumbs.value = {}
    return
  }
  loading.value = true
  error.value = ''
  try {
    const nums = questionNumbers.value
    const res = await Promise.all(
      nums.map((n) => api.imagesList(imagesRoot.value, n).catch(() => ({ files: [] as ImageFile[] }))),
    )
    const c: Record<number, number> = {}
    const t: Record<number, string> = {}
    nums.forEach((n, i) => {
      const list = (res[i] && res[i].files) || []
      c[n] = list.length
      if (list.length) t[n] = mediaUrl(list[0].url || list[0].path)
    })
    counts.value = c
    thumbs.value = t
    // 优先把「已有配图的第一道题」选出来，避免打开就是空状态
    if (!selected.value || !c[selected.value]) {
      const withImg = nums.find((n) => c[n] > 0)
      if (withImg) selected.value = withImg
    }
    if (selected.value) await loadCurrent()
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

/** 读取当前选中题目的图片明细 */
async function loadCurrent() {
  if (!imagesRoot.value || !selected.value) {
    files.value = []
    return
  }
  try {
    const r = await api.imagesList(imagesRoot.value, selected.value)
    files.value = r.files || []
    counts.value = { ...counts.value, [selected.value]: files.value.length }
    if (files.value.length) thumbs.value = { ...thumbs.value, [selected.value]: mediaUrl(files.value[0].url || files.value[0].path) }
  } catch (e) {
    files.value = []
    error.value = errText(e)
  }
}

function select(n: number) {
  selected.value = n
  preview.value = null
  void loadCurrent()
}

/** 添加图片：选择后复制进 图片/<题号>/ */
async function addImages(paths: string[]) {
  if (!paths.length || !selected.value) return
  try {
    const r = await api.imagesAssign(imagesRoot.value, selected.value, paths)
    files.value = r.files || []
    counts.value = { ...counts.value, [selected.value]: files.value.length }
    if (files.value.length) thumbs.value = { ...thumbs.value, [selected.value]: mediaUrl(files.value[0].url || files.value[0].path) }
    ui.notify('已添加 ' + paths.length + ' 张图片到第 ' + selected.value + ' 题', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function removeFile(f: ImageFile) {
  try {
    const r = await api.imagesDelete(imagesRoot.value, selected.value, [f.name])
    files.value = r.files || []
    counts.value = { ...counts.value, [selected.value]: files.value.length }
    if (files.value.length) thumbs.value = { ...thumbs.value, [selected.value]: mediaUrl(files.value[0].url || files.value[0].path) }
    else delete thumbs.value[selected.value]
    preview.value = null
    ui.notify('已删除 ' + f.name, 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

/** 从 PDF 自动抽取配图并按图 bbox 归属题目 */
async function autofill() {
  if (!source.pdf) {
    ui.notify('自动抽取需要先在「① 选择来源」里选定试卷 PDF', 'warn')
    return
  }
  if (!hasQuestions.value) {
    ui.notify('还没有题目数据，请先完成识别与核对', 'warn')
    return
  }
  autofillRunning.value = true
  try {
    const r = await api.imagesAutofill(source.pdf, imagesRoot.value, review.questions)
    assigned.value = r.assigned || {}
    const total = Object.keys(assigned.value).reduce((s, k) => s + (assigned.value[k] || []).length, 0)
    ui.notify('自动归属完成，共 ' + total + ' 张图片', 'success')
    await refreshAll()
  } catch (e) {
    ui.notify(errText(e), 'error')
  } finally {
    autofillRunning.value = false
  }
}
</script>

<template>
  <div class="page">
    <!-- 工具条 -->
    <section class="card">
      <div class="card-head">
        <h2>
          题目配图
          <span class="sub">点选题目 → 添加/删除图片；所有图片可视化预览</span>
        </h2>
        <button class="btn primary" :disabled="autofillRunning || !source.pdf" @click="autofill">
          <span v-if="autofillRunning" class="spinner"></span>
          从 PDF 自动抽取配图
        </button>
      </div>

      <div class="grid-2">
        <div class="field">
          <label class="flabel">图片根目录<span class="tip">（每题的图放在 图片/题号/ 下）</span></label>
          <div class="row">
            <input v-model="imagesRoot" type="text" placeholder="例如 D:\错题集\图片" />
            <PickerButton kind="dir" label="浏览…"
                          @picked="(paths) => { if (paths.length) imagesRoot = paths[0] }" />
          </div>
        </div>
        <div class="field">
          <label class="flabel">当前共 {{ totalImages }} 张配图</label>
          <div class="row">
            <button class="btn" :disabled="!imagesRoot || loading" @click="refreshAll">
              {{ loading ? '正在扫描…' : '重新扫描' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="assignedRows.length" class="banner ok">
        <div>
          <strong>自动抽取结果：</strong>
          <span v-for="r in assignedRows" :key="r.qno" class="assigned">
            第 {{ r.qno }} 题 {{ r.count }} 张
          </span>
        </div>
      </div>
      <div v-if="error" class="banner error">
        <div>{{ error }}</div>
      </div>
    </section>

    <!-- 题目缩略图墙 -->
    <section class="card">
      <div class="card-head">
        <h2>按题目查看配图</h2>
        <span class="sub">{{ hasQuestions ? '题号来自本次识别结果' : '尚未识别，先列出 1~20 题' }}</span>
      </div>

      <div v-if="loading && !Object.keys(counts).length" class="empty">
        <span class="spinner"></span> 正在扫描各题配图…
      </div>
      <div v-else class="qgrid">
        <button
          v-for="n in questionNumbers"
          :key="n"
          class="qtile"
          :class="{ active: n === selected, has: (counts[n] || 0) > 0 }"
          @click="select(n)"
        >
          <div class="qtile-head">
            <span class="qno">第 {{ n }} 题</span>
            <span class="cnt" :class="{ zero: !(counts[n] || 0) }">{{ counts[n] || 0 }} 张</span>
          </div>
          <div class="thumb">
            <img v-if="thumbs[n]" :src="thumbs[n]" :alt="'第' + n + '题配图'" loading="lazy" />
            <span v-else class="none">无配图</span>
          </div>
        </button>
      </div>
    </section>

    <!-- 当前题图片明细 -->
    <section v-if="selected" class="card">
      <div class="card-head">
        <h2>第 {{ selected }} 题 的配图（{{ files.length }} 张）</h2>
        <div class="row">
          <PickerButton
            kind="images"
            :label="'添加图片到第 ' + selected + ' 题…'"
            variant="primary"
            :multi="true"
            :disabled="!imagesRoot"
            @picked="addImages"
          />
        </div>
      </div>

      <EmptyHint
        v-if="!files.length"
        title="这道题还没有配图"
        text="可以点右上角「添加图片到第 N 题…」手动选图，或点上方「从 PDF 自动抽取配图」自动抽取（电子版试卷效果最好）。"
      />
      <div v-else class="imggrid">
        <figure v-for="f in files" :key="f.name" class="imgcard">
          <img :src="mediaUrl(f.url || f.path)" :alt="f.name" loading="lazy" @click="preview = f" />
          <figcaption>
            <span class="fname" :title="f.name">{{ f.name }}</span>
            <span class="muted small">{{ sizeText(f.size) }}</span>
            <button class="btn mini danger" @click.stop="removeFile(f)">删除</button>
          </figcaption>
        </figure>
      </div>
    </section>

    <!-- 大图预览 -->
    <div v-if="preview" class="lightbox" @click="preview = null">
      <img :src="mediaUrl(preview.url || preview.path)" :alt="preview.name" />
      <div class="lb-bar">
        <span>{{ preview.name }}</span>
        <span class="spacer"></span>
        <button class="btn mini" @click.stop="preview = null">关闭</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.assigned {
  display: inline-block;
  margin-right: 12px;
}
.tip {
  color: var(--c-text-3);
  font-weight: 400;
}
.empty {
  padding: 26px;
  text-align: center;
  color: var(--c-text-3);
}

/* ===== 题目缩略图墙 ===== */
.qgrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
}
.qtile {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  background: var(--c-surface);
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.qtile:hover {
  border-color: var(--c-primary);
}
.qtile.active {
  border-color: var(--c-primary);
  box-shadow: 0 0 0 3px var(--c-primary-soft);
}
.qtile-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.qno {
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text);
}
.cnt {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--c-green-soft);
  color: var(--c-green);
}
.cnt.zero {
  background: var(--c-surface-2);
  color: var(--c-text-3);
}
.thumb {
  height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--c-surface-2);
  border-radius: var(--r-sm);
  overflow: hidden;
}
.thumb img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.thumb .none {
  font-size: 12px;
  color: var(--c-text-3);
}

/* ===== 图片明细 ===== */
.imggrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.imgcard {
  margin: 0;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--c-surface);
}
.imgcard img {
  display: block;
  width: 100%;
  height: 150px;
  object-fit: contain;
  background: var(--c-surface-2);
  cursor: zoom-in;
}
.imgcard figcaption {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-top: 1px solid var(--c-border);
}
.fname {
  font-size: 12px;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 大图预览 ===== */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 60;
  background: rgba(17, 22, 28, 0.86);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 28px;
  cursor: zoom-out;
}
.lightbox img {
  max-width: 94vw;
  max-height: 82vh;
  background: #fff;
  border-radius: 6px;
}
.lb-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 94vw;
  color: #fff;
  font-size: 13px;
}
</style>
