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

// ③ 题目配图：按题号查看/添加/删除图片，以及从 PDF 自动抽取归属。

const settings = useSettingsStore()
const review = useReviewStore()
const source = useSourceStore()
const ui = useUiStore()

const imagesRoot = ref('')
const qno = ref(1)
const files = ref<ImageFile[]>([])
const loading = ref(false)
const error = ref('')

const autofillRunning = ref(false)
const autofillError = ref('')
const assigned = ref<Record<string, string[]>>({})

const questionNumbers = computed(() => review.questions.map((q) => q.qno).sort((a, b) => a - b))
const hasQuestions = computed(() => questionNumbers.value.length > 0)

/** 自动抽取结果按题号排序展示 */
const assignedRows = computed(() =>
  Object.keys(assigned.value)
    .map((k) => ({ qno: Number(k), count: (assigned.value[k] || []).length }))
    .sort((a, b) => a.qno - b.qno),
)

onMounted(async () => {
  if (!settings.loaded) await settings.load()
  imagesRoot.value = settings.settings.images_root || ''
  if (hasQuestions.value) qno.value = questionNumbers.value[0]
  if (imagesRoot.value) void load()
})

watch(qno, () => {
  if (imagesRoot.value) void load()
})

watch(imagesRoot, (v) => {
  settings.patch({ images_root: v })
  if (v) void load()
})

/** 列出当前题目的图片 */
async function load() {
  if (!imagesRoot.value) {
    error.value = '还没有设置「图片根目录」，请先到「⑥ 设置」里填写。'
    files.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const r = await api.imagesList(imagesRoot.value, Number(qno.value) || 0)
    files.value = r.files || []
  } catch (e) {
    files.value = []
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

/** 添加图片：选择后复制进 图片/<题号>/ */
async function addImages(paths: string[]) {
  if (!paths.length) return
  try {
    const r = await api.imagesAssign(imagesRoot.value, Number(qno.value) || 0, paths)
    files.value = r.files || []
    ui.notify('已添加 ' + paths.length + ' 张图片到第 ' + qno.value + ' 题', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function removeFile(name: string) {
  try {
    const r = await api.imagesDelete(imagesRoot.value, Number(qno.value) || 0, [name])
    files.value = r.files || []
    ui.notify('已删除 ' + name, 'success')
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
  autofillError.value = ''
  try {
    const r = await api.imagesAutofill(source.pdf, imagesRoot.value, review.questions)
    assigned.value = r.assigned || {}
    const total = Object.keys(assigned.value).reduce((sum, k) => sum + (assigned.value[k] || []).length, 0)
    ui.notify('自动归属完成，共 ' + total + ' 张图片', 'success')
    await load()
  } catch (e) {
    autofillError.value = errText(e)
  } finally {
    autofillRunning.value = false
  }
}
</script>

<template>
  <div class="page">
    <section class="card">
      <div class="card-head">
        <h2>
          题目配图
          <span class="sub">图片统一经 /api/media 读取，不直接暴露文件路径</span>
        </h2>
        <button class="btn" :disabled="autofillRunning || !source.pdf" @click="autofill">
          <span v-if="autofillRunning" class="spinner"></span>
          从 PDF 自动抽取配图
        </button>
      </div>

      <div class="grid-2">
        <div class="field">
          <label class="flabel">图片根目录</label>
          <div class="row">
            <input v-model="imagesRoot" type="text" placeholder="例如 D:\错题集\图片" />
            <PickerButton
              kind="dir"
              label="浏览…"
              @picked="(paths) => { if (paths.length) imagesRoot = paths[0] }"
            />
          </div>
        </div>
        <div class="field">
          <label class="flabel">题号</label>
          <select v-if="hasQuestions" v-model.number="qno">
            <option v-for="n in questionNumbers" :key="n" :value="n">第 {{ n }} 题</option>
          </select>
          <input v-else v-model.number="qno" type="number" min="1" placeholder="题号" />
        </div>
      </div>

      <div class="btn-row">
        <PickerButton
          kind="images"
          label="添加图片…"
          variant="primary"
          :multi="true"
          :disabled="!imagesRoot"
          @picked="addImages"
        />
        <button class="btn" :disabled="!imagesRoot" @click="load">刷新列表</button>
      </div>

      <div v-if="loading" class="empty"><span class="spinner"></span> 正在读取图片…</div>
      <div v-else-if="error" class="banner error">
        <div>{{ error }}</div>
      </div>
      <div v-else-if="files.length" class="gallery">
        <figure v-for="f in files" :key="f.name" class="item">
          <img :src="mediaUrl(f.url || f.path)" :alt="f.name" loading="lazy" />
          <figcaption>
            <div class="fname" :title="f.name">{{ f.name }}</div>
            <div class="muted">{{ sizeText(f.size) }}</div>
            <button class="btn mini danger" @click="removeFile(f.name)">删除</button>
          </figcaption>
        </figure>
      </div>
      <EmptyHint
        v-else
        :title="'第 ' + qno + ' 题还没有配图'"
        text="可以用「添加图片…」手动添加，电子版试卷也可以直接「从 PDF 自动抽取配图」。"
      />
    </section>

    <section v-if="autofillRunning || autofillError || assignedRows.length" class="card">
      <div class="card-head"><h2>自动抽取结果</h2></div>
      <div v-if="autofillRunning" class="empty"><span class="spinner"></span> 正在按图片位置归属题目…</div>
      <div v-else-if="autofillError" class="banner error"><div>{{ autofillError }}</div></div>
      <template v-else>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead>
              <tr><th>题号</th><th>自动归属图片数</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in assignedRows" :key="row.qno">
                <td class="num">第 {{ row.qno }} 题</td>
                <td class="num">{{ row.count }} 张</td>
                <td>
                  <button class="btn mini" @click="qno = row.qno">查看该题图片</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="banner info">自动归属结果仅供参考，请抽查确认后再生成本次错题集。</div>
      </template>
    </section>
  </div>
</template>

<style scoped>
.gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.item {
  margin: 0;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 8px;
  background: var(--c-surface-2);
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: center;
}
.item img {
  width: 100%;
  height: 110px;
  object-fit: contain;
  background: #fff;
  border-radius: var(--r-sm);
}
.item figcaption {
  width: 100%;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
}
.fname {
  font-size: 12px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
