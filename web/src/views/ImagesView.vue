<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, errText, mediaUrl } from '@/api'
import type { ImageFile, QuestionOut, RegionOut } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import PickerButton from '@/components/PickerButton.vue'
import RegionPane from '@/components/RegionPane.vue'
import { useReviewStore } from '@/stores/review'
import { useSettingsStore } from '@/stores/settings'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'
import { sizeText } from '@/utils/format'

// ③ 题目配图（与「② 题目核对」完全相同的分栏逻辑）
//   · 每一道题占一行：**左侧**是题目本身 + 拖放区（把图片拖进来即可配图），
//     **右侧**是这道题在原始试卷上的裁剪原图，鼠标悬停出现放大镜。
//   · 图片素材库平铺在页面顶部的横向条里，拖到左边任意题目上即可；
//     也支持「点一下图片选中 → 点一下题目」的两步操作，方便不习惯拖拽的老师。
//   · 「从 PDF 自动抽取配图」抽出来的图会自动落到对应题目；
//     换一份试卷重新抽取时，会先清掉上一份试卷自动抽取的旧图（不会留残影）。

const settings = useSettingsStore()
const review = useReviewStore()
const source = useSourceStore()
const ui = useUiStore()

const imagesRoot = ref('')
const library = ref<ImageFile[]>([])
const assignMap = ref<Record<string, string[]>>({})
const autoSource = ref<{ pdf: string; name: string; at: string; count: number } | null>(null)
const loading = ref(false)
const error = ref('')
const notes = ref<string[]>([])
const autofillRunning = ref(false)
const preview = ref<ImageFile | null>(null)
const dragging = ref('')
const picked = ref('')
const dragOverQno = ref(0)

/** 有识别结果就按识别到的题号逐题显示；否则用「已分配过的题号 + 1~20」兜底 */
const slots = computed(() => {
  if (review.questions.length) {
    return review.questions.map((q) => ({ qno: q.qno, stem: q.stem || '', regions: q.regions || [] }))
  }
  const keys = Object.keys(assignMap.value).map((k) => Number(k)).filter((n) => n > 0)
  const set = new Set<number>(keys)
  for (let i = 1; i <= 20; i += 1) set.add(i)
  return Array.from(set)
    .sort((a, b) => a - b)
    .map((n) => ({ qno: n, stem: '', regions: [] as RegionOut[] }))
})

const pdfPath = computed(() => review.sourceInfo?.path || source.pdf || '')
const assignedTotal = computed(() =>
  Object.values(assignMap.value).reduce((s, list) => s + (list || []).length, 0),
)
const byName = computed(() => {
  const m: Record<string, ImageFile> = {}
  library.value.forEach((f) => {
    m[f.name] = f
  })
  return m
})

function filesOf(qno: number): ImageFile[] {
  const names = assignMap.value[String(qno)] || []
  return names.map((n) => byName.value[n]).filter(Boolean) as ImageFile[]
}

function stemPreview(q: { stem: string }): string {
  const t = (q.stem || '').replace(/\s+/g, ' ').trim()
  return t.length > 90 ? t.slice(0, 90) + '…' : t
}

onMounted(async () => {
  if (!settings.loaded) await settings.load()
  imagesRoot.value = settings.settings.images_root || ''
  await refresh()
})

watch(imagesRoot, (v) => {
  settings.patch({ images_root: v })
  void refresh()
})

/** 读取图片库与分配表（后端会自动把旧的 图片/<题号>/ 迁移过来） */
async function refresh() {
  if (!imagesRoot.value) {
    error.value = '还没有设置「图片根目录」，请先到「⑥ 设置」里填写，或点右侧「浏览…」。'
    library.value = []
    assignMap.value = {}
    return
  }
  loading.value = true
  error.value = ''
  try {
    const r = await api.imagesLibrary(imagesRoot.value)
    library.value = r.files || []
    assignMap.value = r.assign || {}
    autoSource.value = r.auto_source || null
    notes.value = (r.notes || []).filter((n) => !n.endsWith('_已迁移到平铺目录'))
    if (notes.value.length) ui.notify(notes.value.join('；'), 'success')
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

function onDragStart(name: string, ev: DragEvent) {
  dragging.value = name
  picked.value = name
  if (ev.dataTransfer) {
    ev.dataTransfer.effectAllowed = 'copy'
    ev.dataTransfer.setData('text/plain', name)
  }
}

function onDrop(qno: number) {
  const name = dragging.value || picked.value
  dragOverQno.value = 0
  if (!name) {
    ui.notify('请先把上方素材库里的图片拖过来，或先点选一张图片', 'warn')
    return
  }
  void assignTo(qno, [name])
}

async function assignTo(qno: number, names: string[]) {
  try {
    await api.imagesAssign(imagesRoot.value, qno, names)
    const m = { ...assignMap.value }
    const cur = (m[String(qno)] || []).slice()
    names.forEach((n) => {
      if (!cur.includes(n)) cur.push(n)
    })
    m[String(qno)] = cur
    assignMap.value = m
    ui.notify('已把 ' + names.length + ' 张图片配到第 ' + qno + ' 题', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function unassign(qno: number, name: string) {
  try {
    await api.imagesUnassign(imagesRoot.value, qno, [name])
    const m = { ...assignMap.value }
    m[String(qno)] = (m[String(qno)] || []).filter((n) => n !== name)
    assignMap.value = m
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function clearQno(qno: number) {
  const names = (assignMap.value[String(qno)] || []).slice()
  if (!names.length) return
  try {
    await api.imagesUnassign(imagesRoot.value, qno, names)
    const m = { ...assignMap.value }
    m[String(qno)] = []
    assignMap.value = m
    ui.notify('已清空第 ' + qno + ' 题的配图', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

/** 从磁盘导入图片：直接放进图片库（不再建子文件夹） */
async function importImages(paths: string[]) {
  if (!paths.length) return
  try {
    await refresh()
    await api.imagesAssign(imagesRoot.value, slots.value[0]?.qno || 1, paths)
    await refresh()
    ui.notify('已导入 ' + paths.length + ' 张图片到图片库', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function deleteImage(f: ImageFile) {
  try {
    await api.imagesDelete(imagesRoot.value, [f.name])
    preview.value = null
    await refresh()
    ui.notify('已删除 ' + f.name, 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

/** 清空图片库：删除所有图片与分配关系，回到“默认无图片”的状态 */
async function clearLibrary() {
  if (!library.value.length) {
    ui.notify('图片库已经是空的', 'warn')
    return
  }
  if (!window.confirm('确定清空图片库吗？将删除「' + imagesRoot.value + '」下的 ' +
    library.value.length + ' 张图片，并清空所有题目的配图（题目配置不受影响）。')) {
    return
  }
  try {
    const r = await api.imagesClear(imagesRoot.value)
    await refresh()
    ui.notify('已清空图片库（删除 ' + r.removed + ' 张）', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function autofill() {
  if (!source.pdf) {
    ui.notify('自动抽取需要先在「① 选择来源」里选定试卷 PDF', 'warn')
    return
  }
  autofillRunning.value = true
  try {
    const r = await api.imagesAutofill(source.pdf, imagesRoot.value)
    const total = Object.keys(r.assigned || {}).reduce((s, k) => s + (r.assigned[k] || []).length, 0)
    let msg = '自动抽取完成，共 ' + total + ' 张图片并已配到对应题目'
    if (r.purged) {
      msg += '（已清掉上一轮自动抽取的 ' + r.purged + ' 张' +
        (r.previous_pdf ? '，来自「' + r.previous_pdf + '」' : '') + '）'
    }
    ui.notify(msg, 'success', 7000)
    await refresh()
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
          <span class="sub">左侧题目 + 拖放区，右侧裁切原图；把素材库里的图拖到题目上即可</span>
        </h2>
        <button class="btn primary" :disabled="autofillRunning || !source.pdf" @click="autofill">
          <span v-if="autofillRunning" class="spinner"></span>
          从 PDF 自动抽取配图
        </button>
      </div>

      <div class="grid-2">
        <div class="field">
          <label class="flabel">图片根目录<span class="tip">（图片平铺放在这里）</span></label>
          <div class="row">
            <input v-model="imagesRoot" type="text" placeholder="例如 D:\错题集\图片" />
            <PickerButton kind="dir" label="浏览…"
                          @picked="(paths) => { if (paths.length) imagesRoot = paths[0] }" />
          </div>
        </div>
        <div class="field">
          <label class="flabel">
            图片库 {{ library.length }} 张 · 已配 {{ assignedTotal }} 处
          </label>
          <div class="row">
            <PickerButton kind="images" label="添加图片…" :multi="true" :disabled="!imagesRoot"
                          @picked="importImages" />
            <button class="btn" :disabled="!imagesRoot || loading" @click="refresh">
              {{ loading ? '扫描中…' : '重新扫描' }}
            </button>
            <button class="btn ghost" :disabled="!imagesRoot || !library.length" @click="clearLibrary">
              清空图片库
            </button>
          </div>
        </div>
      </div>

      <div v-if="autoSource && autoSource.count" class="autosrc">
        自动抽取来源：<strong>{{ autoSource.name || autoSource.pdf }}</strong>
        （{{ autoSource.count }} 张<template v-if="autoSource.at"> · {{ autoSource.at }}</template>）
        <span class="tip">换试卷后重新抽取会自动清掉这批旧图</span>
      </div>

      <div v-if="!review.allVerified" class="banner warn">
        <div>
          第②步「题目核对」还没有全部勾选完成，配图可能对不上题目：
          请回到「题目核对」逐题勾选「已核对」，再点「确认核验」。
        </div>
      </div>

      <div v-if="error" class="banner error"><div>{{ error }}</div></div>
    </section>

    <!-- 图片素材库：横向条，拖到下面的题目上即可 -->
    <section class="card">
      <div class="card-head">
        <h2>
          图片素材库
          <span class="sub">
            {{ picked ? '已选中「' + picked + '」，点题目即可配图' : '按住图片拖到下面任意题目上' }}
          </span>
        </h2>
      </div>
      <EmptyHint
        v-if="!library.length && !loading"
        title="图片库还是空的"
        text="点上方「添加图片…」从电脑里选图，或点「从 PDF 自动抽取配图」自动生成。"
      />
      <div v-else class="libstrip">
        <figure
          v-for="f in library"
          :key="f.name"
          class="libcard"
          :class="{ picked: picked === f.name }"
          draggable="true"
          @dragstart="onDragStart(f.name, $event)"
          @dragend="dragging = ''"
          @click="picked = f.name"
        >
          <img :src="mediaUrl(f.url || f.path)" :alt="f.name" loading="lazy" />
          <figcaption>
            <span class="fname" :title="f.name">{{ f.name }}</span>
            <span class="rowmini">
              <span v-if="f.auto" class="tag">自动</span>
              <span class="muted small">{{ sizeText(f.size) }}</span>
              <span class="spacer"></span>
              <button class="btn mini" @click.stop="preview = f">看</button>
              <button class="btn mini danger" @click.stop="deleteImage(f)">删</button>
            </span>
          </figcaption>
        </figure>
      </div>
    </section>

    <!-- 每题一行：左=题目与拖放区，右=裁剪原图（与核对页同一套逻辑） -->
    <div class="pair-grid">
      <template v-for="q in slots" :key="q.qno">
        <div
          class="qslot"
          :class="{ over: dragOverQno === q.qno, has: filesOf(q.qno).length > 0 }"
          @dragover.prevent="dragOverQno = q.qno"
          @dragleave="dragOverQno = 0"
          @drop.prevent="onDrop(q.qno)"
          @click="onDrop(q.qno)"
        >
          <div class="qslot-head">
            <span class="qno">第 {{ q.qno }} 题</span>
            <span class="cnt" :class="{ zero: !filesOf(q.qno).length }">{{ filesOf(q.qno).length }} 张</span>
            <span class="spacer"></span>
            <button
              v-if="filesOf(q.qno).length"
              class="btn mini ghost"
              @click.stop="clearQno(q.qno)"
            >清空本题</button>
          </div>

          <div v-if="q.stem" class="stem-prev">{{ stemPreview(q) }}</div>

          <div class="dropzone" :class="{ empty: !filesOf(q.qno).length }">
            <template v-if="filesOf(q.qno).length">
              <figure v-for="f in filesOf(q.qno)" :key="f.name" class="thumb">
                <img :src="mediaUrl(f.url || f.path)" :alt="f.name" loading="lazy"
                     @click.stop="preview = f" />
                <button class="rm" title="移出本题" @click.stop="unassign(q.qno, f.name)">×</button>
              </figure>
            </template>
            <span v-else class="droptip">
              {{ picked ? '点这里把「' + picked + '」配到第 ' + q.qno + ' 题' : '把图片拖到这里' }}
            </span>
          </div>
        </div>

        <!-- 裁剪原图 + 悬停放大镜（与「② 题目核对」共用 RegionPane） -->
        <RegionPane :qno="q.qno" :regions="q.regions" :pdf="pdfPath" />
      </template>
    </div>

    <!-- 底部：下一步 -->
    <div class="nextbar">
      <span class="muted">
        配图完成后进入下一步生成错题集；也可以先跳过配图直接生成。
      </span>
      <span class="spacer"></span>
      <RouterLink class="btn" to="/review">返回题目核对</RouterLink>
      <RouterLink class="btn primary lg" to="/generate">下一步：生成 →</RouterLink>
    </div>

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
.tip {
  color: var(--c-text-3);
  font-weight: 400;
}
.autosrc {
  margin-top: 10px;
  font-size: 13px;
  color: var(--c-text-2);
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  padding: 7px 10px;
}
.autosrc .tip {
  margin-left: 8px;
  font-size: 12px;
}

/* ===== 素材库（横向条） ===== */
.libstrip {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 6px;
}
.libcard {
  flex: none;
  width: 152px;
  margin: 0;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--c-surface);
  cursor: grab;
}
.libcard.picked {
  border-color: var(--c-primary);
  box-shadow: 0 0 0 3px var(--c-primary-soft);
}
.libcard img {
  display: block;
  width: 100%;
  height: 104px;
  object-fit: contain;
  background: var(--c-surface-2);
}
.libcard figcaption {
  padding: 5px 7px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.fname {
  font-size: 12px;
  color: var(--c-text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rowmini {
  display: flex;
  align-items: center;
  gap: 4px;
}
.tag {
  font-size: 11px;
  padding: 0 5px;
  border-radius: 999px;
  color: var(--c-primary);
  background: var(--c-primary-soft);
}

/* ===== 每题一行：左=题目与拖放区，右=裁剪原图 ===== */
.pair-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px 16px;
  align-items: start;
}
.qslot {
  min-width: 0;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--c-border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  padding: 12px 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
  scroll-margin-top: 80px;
}
.qslot.has {
  border-left-color: var(--c-green);
}
.qslot.over {
  border-color: var(--c-primary);
  background: var(--c-primary-soft);
}
.qslot-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.qno {
  font-size: 15px;
  font-weight: 600;
}
.cnt {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--c-green-soft);
  color: var(--c-green);
}
.cnt.zero {
  background: var(--c-surface-2);
  color: var(--c-text-3);
}
.stem-prev {
  font-size: 13px;
  line-height: 1.6;
  color: var(--c-text-2);
  background: var(--c-surface-2);
  border-radius: var(--r-sm);
  padding: 7px 10px;
}
.dropzone {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 84px;
  border: 1px dashed var(--c-border-strong);
  border-radius: var(--r-md);
  padding: 8px;
  align-items: center;
  justify-content: center;
}
.dropzone.empty {
  color: var(--c-text-3);
}
.droptip {
  font-size: 12px;
  text-align: center;
}
.thumb {
  position: relative;
  margin: 0;
  width: 76px;
  height: 76px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--c-surface-2);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  cursor: zoom-in;
}
.thumb .rm {
  position: absolute;
  top: 0;
  right: 0;
  width: 18px;
  height: 18px;
  line-height: 1;
  border: none;
  border-radius: 0 0 0 6px;
  background: rgba(198, 40, 40, 0.85);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}

/* ===== 大图预览 ===== */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 90;
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

.nextbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  margin-bottom: 80px;
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
}

@media (max-width: 1200px) {
  .pair-grid {
    grid-template-columns: 1fr;
  }
}
</style>
