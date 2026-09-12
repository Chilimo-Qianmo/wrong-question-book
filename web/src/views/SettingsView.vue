<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errText } from '@/api'
import type { Settings } from '@/api/types'
import PickerButton from '@/components/PickerButton.vue'
import { defaultSettings, useSettingsStore } from '@/stores/settings'
import { useSourceStore } from '@/stores/source'
import { useUiStore } from '@/stores/ui'

// ⑥ 设置：GET/PUT /api/settings，含目录默认值与版式常量。

const settings = useSettingsStore()
const source = useSourceStore()
const ui = useUiStore()

const savedTip = ref('')

onMounted(async () => {
  if (!settings.loaded) await settings.load()
  if (settings.loaded) source.applySettingsDefaults(settings.settings)
})

function onPickedOutDir(paths: string[]) {
  if (paths.length) settings.patch({ out_dir: paths[0] })
}

function onPickedImagesRoot(paths: string[]) {
  if (paths.length) settings.patch({ images_root: paths[0] })
}

async function save() {
  const ok = await settings.save()
  if (ok) {
    savedTip.value = '已保存'
    source.applySettingsDefaults(settings.settings)
    ui.notify('设置已保存', 'success')
    window.setTimeout(() => (savedTip.value = ''), 2500)
  } else {
    ui.notify('保存失败：' + (settings.error || '未知错误'), 'error')
  }
}

function restoreDefaults() {
  settings.settings = { ...defaultSettings } as Settings
  ui.notify('已恢复默认值，记得点保存', 'warn')
}

/* ===== 系统诊断：出问题时把结果发出来即可定位 ===== */
const diagRunning = ref(false)
const diagText = ref('')

async function runDiagnose() {
  diagRunning.value = true
  diagText.value = ''
  try {
    const r = await api.diagnose(source.pdf || undefined)
    diagText.value = JSON.stringify(r, null, 2)
    ui.notify('诊断完成', 'success')
  } catch (e) {
    diagText.value = errText(e)
    ui.notify(errText(e), 'error')
  } finally {
    diagRunning.value = false
  }
}

async function copyDiagnose() {
  if (!diagText.value) return
  try {
    await navigator.clipboard.writeText(diagText.value)
    ui.notify('诊断结果已复制', 'success')
  } catch {
    ui.notify('复制失败，请手动选中复制', 'warn')
  }
}
</script>

<template>
  <div class="page">
    <section v-if="settings.error" class="banner error">
      <div>
        <strong>读取/保存设置失败：</strong>{{ settings.error }}
        <button class="btn mini" @click="settings.load()">重试</button>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>
          目录与默认值
          <span class="sub">这些值会作为各页面的默认输入</span>
        </h2>
        <button class="btn" :disabled="settings.loading" @click="settings.load()">重新加载</button>
      </div>

      <div class="field">
        <label class="flabel">默认输出目录</label>
        <div class="row">
          <input v-model="settings.settings.out_dir" type="text" placeholder="例如 D:\错题集" />
          <PickerButton kind="dir" label="浏览…" @picked="onPickedOutDir" />
        </div>
      </div>

      <div class="field">
        <label class="flabel">图片根目录</label>
        <div class="row">
          <input v-model="settings.settings.images_root" type="text" placeholder="例如 D:\错题集\图片" />
          <PickerButton kind="dir" label="浏览…" @picked="onPickedImagesRoot" />
        </div>
      </div>

      <div class="grid-2">
        <div class="field">
          <label class="flabel">默认班级</label>
          <input v-model="settings.settings.class_name" type="text" placeholder="例如 14班" />
        </div>
        <div class="field">
          <label class="flabel">默认考试标题</label>
          <input v-model="settings.settings.exam_title" type="text" placeholder="例如 2026 届高三摸底考试" />
        </div>
      </div>

      <div class="field">
        <label class="flabel">行为</label>
        <label class="check">
          <input v-model="settings.settings.keep_images" type="checkbox" />
          保留图片缓存（生成后不清理中间图片）
        </label>
        <label class="check">
          <input v-model="settings.settings.auto_open_after_generate" type="checkbox" />
          生成后自动打开输出目录
        </label>
      </div>
    </section>

    <section class="card">
      <div class="card-head">
        <h2>
          版式常量
          <span class="sub">影响生成的 Word 文档排版</span>
        </h2>
      </div>
      <div class="grid-2">
        <div class="field">
          <label class="flabel">正文字体</label>
          <input v-model="settings.settings.font_name" type="text" placeholder="宋体" />
        </div>
        <div class="field">
          <label class="flabel">字号（pt）</label>
          <input v-model.number="settings.settings.body_size" type="number" step="0.5" min="6" max="24" />
        </div>
        <div class="field">
          <label class="flabel">行距（倍数）</label>
          <input v-model.number="settings.settings.line_spacing" type="number" step="0.05" min="0.8" max="3" />
        </div>
        <div class="field">
          <label class="flabel">页边距（cm）</label>
          <input v-model.number="settings.settings.page_margin_cm" type="number" step="0.1" min="0.5" max="5" />
        </div>
      </div>
    </section>

    <section class="card">
      <div class="card-head"><h2>运行环境</h2></div>
      <div class="kv">
        <div class="item">
          <span class="k">后端状态</span>
          <span class="v">{{ ui.online === null ? '检测中…' : ui.online ? '已连接' : '未连接' }}</span>
        </div>
        <div class="item"><span class="k">版本</span><span class="v small">{{ ui.version || '—' }}</span></div>
        <div class="item">
          <span class="k">pdfplumber（电子版解析）</span>
          <span class="v">{{ ui.engine ? (ui.engine.pdfplumber ? '可用' : '缺失') : '—' }}</span>
        </div>
        <div class="item">
          <span class="k">RapidOCR（扫描版）</span>
          <span class="v">{{ ui.engine ? (ui.engine.rapidocr ? '可用' : '缺失') : '—' }}</span>
        </div>
        <div class="item">
          <span class="k">OpenCV（表格线检测）</span>
          <span class="v">{{ ui.engine ? (ui.engine.opencv ? '可用' : '缺失') : '—' }}</span>
        </div>
      </div>
      <div class="btn-row env">
        <button class="btn" @click="ui.checkHealth()">重新检测</button>
        <button class="btn primary" :disabled="diagRunning" @click="runDiagnose">
          <span v-if="diagRunning" class="spinner"></span>
          系统诊断
        </button>
        <button v-if="diagText" class="btn ghost" @click="copyDiagnose">复制结果</button>
      </div>

      <div v-if="diagText" class="diag">
        <div class="muted small">
          诊断内容包含目录、可写性与一次真实裁切测试；出问题时可复制发给开发者定位。
        </div>
        <pre>{{ diagText }}</pre>
      </div>
    </section>

    <div class="footer-actions">
      <button class="btn primary lg" :disabled="settings.saving" @click="save">
        <span v-if="settings.saving" class="spinner"></span>
        保存设置
      </button>
      <button class="btn ghost" @click="restoreDefaults">恢复默认值</button>
      <span v-if="savedTip" class="oktip">{{ savedTip }}</span>
    </div>
  </div>
</template>

<style scoped>
.diag {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.diag pre {
  max-height: 320px;
  overflow: auto;
  padding: 10px 12px;
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
<style scoped>
.env {
  margin-top: 12px;
}
.footer-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}
.oktip {
  color: var(--c-green);
  font-size: 13px;
}
</style>
