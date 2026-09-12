<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import type { DroppedText, QuestionOut } from '@/api/types'
import { mediaUrl } from '@/api'
import SourceBadge from './SourceBadge.vue'
import { useReviewStore } from '@/stores/review'
import { useUiStore } from '@/stores/ui'

// 单题核对卡片。
// 说明：q 来自 Pinia store 里的响应式对象，这里直接改它的字段即可同步回全局状态
// （props 顶层是只读的，但嵌套对象是可写的）。
const props = defineProps<{
  q: QuestionOut
  index: number
  flashing?: boolean
}>()

const OPTION_KEYS = ['A', 'B', 'C', 'D']
const ui = useUiStore()

/** 选项键：固定 A/B/C/D，再并上后端返回的多余键（如 E/F） */
const optionKeys = computed(() => {
  const keys = new Set<string>(OPTION_KEYS)
  Object.keys(props.q.options || {}).forEach((k) => keys.add(k))
  return Array.from(keys).sort()
})

const reviewStore = useReviewStore()

/** 修改题号（与已有题号冲突时提示并还原） */
function onQnoChange(ev: Event) {
  const el = ev.target as HTMLInputElement
  const next = Number(el.value)
  if (!reviewStore.setQno(props.q.qno, next)) {
    ui.notify('题号 ' + next + ' 已被占用，或不是有效数字', 'warn')
    el.value = String(props.q.qno)
  }
}

/** 删除本题 */
function removeSelf() {
  if (!window.confirm('确定删除「第 ' + props.q.qno + ' 题」吗？删除后该题不会出现在错题集里。')) return
  reviewStore.removeQuestion(props.q.qno)
  ui.notify('已删除第 ' + props.q.qno + ' 题', 'success')
}

const confLow = computed(() => (props.q.conf || 0) < 0.9)
const hasIssues = computed(() => (props.q.warnings || []).length > 0 || (props.q.dropped || []).length > 0)
// 「已忽略的疑似图/表文字」默认收起，需要时点标题展开（避免核对时被大量信息淹没）
const droppedOpen = ref(false)

/* ===== 题干自动高度 ===== */
const stemEl = ref<HTMLTextAreaElement | null>(null)

function grow() {
  const el = stemEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 4 + 'px'
}

onMounted(() => nextTick(grow))
watch(
  () => props.q.stem,
  () => nextTick(grow),
  { immediate: true },
)

/* ===== 选项编辑（文本域：自动换行 + 自动高度，一次看全） ===== */
const optEls = new Map<string, HTMLTextAreaElement>()

function setOptEl(key: string, el: Element | null) {
  if (el) optEls.set(key, el as HTMLTextAreaElement)
  else optEls.delete(key)
}

/** 让某个文本域按内容自适应高度 */
function growEl(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 2 + 'px'
}

function growOpts() {
  optEls.forEach((el) => growEl(el))
}

function onOptionInput(key: string, ev: Event) {
  const el = ev.target as HTMLTextAreaElement
  growEl(el)
  const value = el.value
  if (value.trim() === '') delete props.q.options[key]
  else props.q.options[key] = value
}

onMounted(() => nextTick(growOpts))
watch(
  () => props.q.options,
  () => nextTick(growOpts),
  { deep: true, immediate: true },
)

/* ===== 配图 ===== */
function removeFigure(index: number) {
  props.q.figures.splice(index, 1)
}

/* ===== 表格（v2.3.3 起不再在本卡片出现，保留函数以兼容旧数据） ===== */
function tableSourceText(source: string): string {
  if (source === 'structured') return '结构化表格'
  if (source === 'manual') return '手工指定'
  return '线框检测'
}

/* ===== 已忽略文本 → 并入题干 ===== */
function absorb(d: DroppedText, index: number) {
  const text = (d.text || '').trim()
  if (text) {
    props.q.stem = props.q.stem ? props.q.stem.replace(/\s+$/, '') + '\n' + text : text
  }
  props.q.dropped.splice(index, 1)
  void nextTick(grow)
}
</script>

<template>
  <article :id="'q-' + q.qno" class="qcard" :class="{ issue: hasIssues, flash: flashing }">
    <header class="qhead">
      <div class="qleft">
        <span class="qno">第</span>
        <input
          class="qnoinput"
          type="number"
          min="1"
          :value="q.qno"
          title="可修改题号（需与答题表列名一致）"
          @change="onQnoChange"
        />
        <span class="qno">题</span>
        <SourceBadge :source="q.source" />
        <span v-if="q.source !== 'manual'" class="conf" :class="{ low: confLow }">
          置信度 {{ Math.round((q.conf || 0) * 100) }}%
        </span>
        <span v-if="q.page" class="pg">第 {{ q.page }} 页</span>
        <span v-if="hasIssues" class="badge orange">需关注</span>
      </div>
      <div class="qright">
        <button class="btn mini danger" title="从错题集中删除这道题" @click="removeSelf">删除本题</button>
        <label class="check">
          <input v-model="q.verified" type="checkbox" />
          已核对
        </label>
      </div>
    </header>

    <div class="field">
      <label class="flabel">题干</label>
      <textarea ref="stemEl" v-model="q.stem" class="stem" rows="2" placeholder="题干内容" @input="grow"></textarea>
    </div>

    <div class="field">
      <label class="flabel">选项</label>
      <div class="options">
        <div v-for="k in optionKeys" :key="k" class="opt">
          <span class="okey">{{ k }}</span>
          <textarea
            :ref="(el) => setOptEl(k, el as Element | null)"
            class="opttext"
            rows="1"
            :value="q.options[k] || ''"
            :placeholder="'选项 ' + k"
            @input="onOptionInput(k, $event)"
          ></textarea>
        </div>
      </div>
    </div>

    <div v-if="(q.figures || []).length" class="field">
      <label class="flabel">配图（{{ q.figures.length }} 张）</label>
      <div class="figs">
        <figure v-for="(f, i) in q.figures" :key="f.id || i" class="fig">
          <img
            v-if="f.url || f.path"
            :src="mediaUrl(f.url || f.path)"
            :alt="'配图 ' + (i + 1)"
            loading="lazy"
          />
          <div v-else class="noimg">配图暂不可预览（第 {{ f.page }} 页）</div>
          <figcaption class="figmeta">
            第 {{ f.page }} 页<template v-if="f.auto"> · 自动抽取</template>
          </figcaption>
          <button class="btn mini ghost" @click="removeFigure(i)">删除</button>
        </figure>
      </div>
    </div>

    <!-- v2.3.3：表格不再单独识别与插入；卷面上的表格会出现在上面的「配图」里，
         需要的话到「③ 题目配图」把它拖到本题即可 -->

    <div v-if="(q.warnings || []).length" class="warns">
      <div v-for="(w, i) in q.warnings" :key="i" class="banner warn">⚠ {{ w }}</div>
    </div>

    <div v-if="(q.dropped || []).length" class="dropped">
      <button class="droptoggle" @click="droppedOpen = !droppedOpen">
        {{ droppedOpen ? '▾' : '▸' }} 已忽略的疑似图/表文字（{{ q.dropped.length }} 条）
      </button>
      <ul v-show="droppedOpen" class="droplist">
        <li v-for="(d, i) in q.dropped" :key="i">
          <div class="dtext">{{ d.text }}</div>
          <div class="dmeta">第 {{ d.page }} 页 · {{ d.reason || '未说明原因' }}</div>
          <button class="btn mini" @click="absorb(d, i)">并入题干</button>
        </li>
      </ul>
    </div>
  </article>
</template>

<style scoped>
.qcard {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-left: 3px solid var(--c-border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  padding: 14px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  scroll-margin-top: 80px;
}
.qcard.issue {
  border-left-color: var(--c-warn-bd);
}
.qcard.flash {
  animation: flash 0.5s ease 3;
  border-color: var(--c-primary);
}
@keyframes flash {
  50% {
    background: var(--c-primary-soft);
  }
}
.qhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--c-border);
}
.qleft {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.qno {
  font-size: 15px;
  font-weight: 600;
}
/* 题号可编辑：方便自编题目或与答题表对齐 */
.qnoinput {
  width: 54px;
  padding: 2px 6px;
  font-size: 14px;
  font-weight: 600;
  text-align: center;
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-sm);
  background: var(--c-surface);
  color: var(--c-text);
}
.qnoinput:focus {
  outline: none;
  border-color: var(--c-primary);
  box-shadow: 0 0 0 3px var(--c-primary-soft);
}
.qright {
  display: flex;
  align-items: center;
  gap: 10px;
}
.conf {
  font-size: 12px;
  color: var(--c-green);
  background: var(--c-green-soft);
  padding: 1px 8px;
  border-radius: 999px;
}
.conf.low {
  color: var(--c-orange);
  background: var(--c-orange-soft);
}
.pg {
  font-size: 12px;
  color: var(--c-text-3);
}
.check.small {
  font-size: 12px;
}
.options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 14px;
}
.opt {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
/* 选项文本域：可换行、随内容自动增高，长选项一次看全 */
.opttext {
  flex: 1 1 auto;
  min-width: 0;
  resize: none;
  overflow: hidden;
  line-height: 1.5;
  padding: 4px 8px;
  border: 1px solid var(--c-border-strong);
  border-radius: var(--r-sm);
  font: inherit;
  font-size: 13px;
  color: var(--c-text);
  background: var(--c-surface);
  field-sizing: content;
}
.opttext:focus {
  outline: none;
  border-color: var(--c-primary);
  box-shadow: 0 0 0 3px var(--c-primary-soft);
}
.okey {
  flex: none;
  margin-top: 5px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--c-surface-2);
  border: 1px solid var(--c-border-strong);
  color: var(--c-text-2);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.figs {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.fig {
  margin: 0;
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 6px;
  background: var(--c-surface-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
  align-items: center;
}
.fig img {
  max-width: 180px;
  max-height: 130px;
  border-radius: var(--r-sm);
  background: #fff;
  object-fit: contain;
}
.figmeta {
  font-size: 11px;
  color: var(--c-text-3);
}
.tables {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tblbox {
  border: 1px solid var(--c-border);
  border-radius: var(--r-md);
  padding: 8px 10px;
  background: var(--c-surface-2);
}
.tblhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.tblimg {
  max-width: 100%;
  max-height: 220px;
  border-radius: var(--r-sm);
  background: #fff;
}
.warns {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dropped {
  border-top: 1px dashed var(--c-border);
  padding-top: 8px;
}
.droptoggle {
  border: none;
  background: none;
  color: var(--c-text-2);
  font-size: 13px;
  cursor: pointer;
  padding: 2px 0;
}
.droptoggle:hover {
  color: var(--c-primary);
}
.droplist {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.droplist li {
  display: grid;
  grid-template-columns: 1fr auto;
  grid-template-areas: 'text btn' 'meta btn';
  gap: 2px 12px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background: var(--c-surface-2);
}
.dtext {
  grid-area: text;
  font-size: 13px;
}
.dmeta {
  grid-area: meta;
  font-size: 11px;
  color: var(--c-text-3);
}
.droplist .btn {
  grid-area: btn;
}
</style>
