<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, errText } from '@/api'
import { subscribeJob, type JobStream } from '@/api/sse'
import type { MergeRequest, MergeResult } from '@/api/types'
import EmptyHint from '@/components/EmptyHint.vue'
import LogPanel from '@/components/LogPanel.vue'
import PickerButton from '@/components/PickerButton.vue'
import ProgressBar from '@/components/ProgressBar.vue'
import { useJobStore } from '@/stores/job'
import { useSettingsStore } from '@/stores/settings'
import { useUiStore } from '@/stores/ui'

// ⑤ 合并：多个错题集文件夹 + 去重/复制选项 + SSE 日志 + 结果。

const job = useJobStore()
const settings = useSettingsStore()
const ui = useUiStore()

const folders = ref<string[]>([])
const outDir = ref('')
const deduplicate = ref(false)
const copySingle = ref(true)
const stream = ref<JobStream | null>(null)

const task = computed(() => job.tasks.merge)
const result = computed(() => (task.value.result || null) as MergeResult | null)
const running = computed(() => task.value.running)

/** 合并前预览：按班级分组、每组文档数、实际输出目录 */
const preview = ref<{
  root: string
  root_name: string
  total_docs: number
  folder_count: number
  groups: { cls: string; folders: string[]; docs: number; out_dir: string }[]
} | null>(null)
const previewing = ref(false)

onMounted(async () => {
  if (!settings.loaded) await settings.load()
  // 合并功能是独立的：输出目录留空时后端会用程序目录下的「错题集合并」
})

onUnmounted(() => {
  stream.value?.close()
  stream.value = null
})

async function refreshPreview() {
  if (!folders.value.length) {
    preview.value = null
    return
  }
  previewing.value = true
  try {
    preview.value = await api.mergePreview(folders.value.slice(), outDir.value)
  } catch (e) {
    preview.value = null
    ui.notify(errText(e), 'warn')
  } finally {
    previewing.value = false
  }
}

function addFolders(paths: string[]) {
  paths.forEach((p) => {
    if (p && !folders.value.includes(p)) folders.value.push(p)
  })
  void refreshPreview()
}

function removeFolder(index: number) {
  folders.value.splice(index, 1)
  void refreshPreview()
}

function clearFolders() {
  folders.value = []
  preview.value = null
}

async function start() {
  if (!folders.value.length) {
    ui.notify('请先添加至少一个错题集文件夹', 'warn')
    return
  }
  stream.value?.close()
  job.reset('merge')
  const req: MergeRequest = {
    folders: folders.value.slice(),
    out_dir: outDir.value,
    deduplicate: deduplicate.value,
    copy_single: copySingle.value,
  }
  try {
    const r = await api.jobsMerge(req)
    job.start('merge', r.job_id)
    job.pushText('merge', '已提交合并任务：' + r.job_id)
    follow(r.job_id)
  } catch (e) {
    job.fail('merge', errText(e))
    ui.notify(errText(e), 'error')
  }
}

function follow(jobId: string) {
  stream.value = subscribeJob(jobId, {
    onLog: (e) => job.pushLog('merge', e),
    onProgress: (p) => job.setProgress('merge', p),
    onResult: (r) => {
      job.setResult('merge', r)
      // MergeResult.logs 是纯文本日志，补进日志面板
      const logs = (r as unknown as MergeResult).logs
      if (Array.isArray(logs)) logs.forEach((line) => job.pushText('merge', String(line)))
    },
    onError: (e) => job.fail('merge', e.message),
    onDone: (d) => job.finish('merge', d.state),
    onFail: (m) => job.pushText('merge', m, 'warn'),
  })
}

async function cancel() {
  if (!task.value.jobId) return
  try {
    await api.jobCancel(task.value.jobId)
    job.pushText('merge', '已请求取消合并任务', 'warn')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}

async function openFolder(path: string) {
  try {
    await api.openPath(path)
    ui.notify('已在资源管理器中打开', 'success')
  } catch (e) {
    ui.notify(errText(e), 'error')
  }
}
</script>

<template>
  <div class="page">
    <section class="card">
      <div class="card-head">
        <h2>
          待合并的错题集文件夹
          <span class="sub">可以选择父目录，后端会自动展开出各班错题集</span>
        </h2>
        <div class="row">
          <button v-if="folders.length" class="btn mini ghost" @click="clearFolders">清空</button>
        </div>
      </div>

      <div class="btn-row">
        <PickerButton kind="dir" label="添加文件夹…" variant="primary" :multi="true" @picked="addFolders" />
      </div>

      <ul v-if="folders.length" class="folderlist">
        <li v-for="(f, i) in folders" :key="f">
          <span class="mono ellip" :title="f">{{ f }}</span>
          <button class="btn mini danger" @click="removeFolder(i)">移除</button>
        </li>
      </ul>
      <EmptyHint v-else title="还没有添加文件夹" text="把上一轮生成的错题集文件夹（或它们的父目录）加进来。" />
    </section>

    <section class="card">
      <div class="card-head"><h2>合并选项</h2></div>
      <div class="grid-2">
        <div class="field">
          <label class="flabel">去重与复制</label>
          <label class="check">
            <input v-model="deduplicate" type="checkbox" />
            按题号去重（同一题只保留一份）
          </label>
          <label class="check">
            <input v-model="copySingle" type="checkbox" />
            复制仅单侧学生文档（某个班独有的学生也一起带过去）
          </label>
        </div>
        <div class="field">
          <label class="flabel">
            输出根目录
            <span class="tip">（留空则自动使用程序目录下的「{{ preview?.root_name || '错题集合并' }}」）</span>
          </label>
          <div class="row">
            <input v-model="outDir" type="text" placeholder="留空 = 程序目录下的「错题集合并」"
                   @change="refreshPreview" />
            <PickerButton kind="dir" label="浏览…"
                          @picked="(paths) => { if (paths.length) { outDir = paths[0]; refreshPreview() } }" />
          </div>
        </div>
      </div>

      <div class="btn-row actions">
        <button class="btn primary lg" :disabled="running || !folders.length" @click="start">
          <span v-if="running" class="spinner"></span>
          {{ running ? '正在合并…' : '开始合并' }}
        </button>
        <button class="btn" :disabled="!folders.length || previewing" @click="refreshPreview">
          {{ previewing ? '分析中…' : '重新分析' }}
        </button>
        <button v-if="running" class="btn danger" @click="cancel">取消任务</button>
      </div>
    </section>

    <!-- 合并前预览：按班级分组，确认无误再合并 -->
    <section v-if="preview" class="card">
      <div class="card-head">
        <h2>
          按班级分组预览
          <span class="sub">合并结果会分别保存到「输出根目录 / 班级」下</span>
        </h2>
        <span class="badge">{{ preview.total_docs }} 份文档</span>
      </div>
      <div class="muted small rootline">
        输出根目录：<span class="mono">{{ preview.root }}</span>
        <button class="btn mini" @click="openFolder(preview.root)">打开</button>
      </div>
      <ul class="groups">
        <li v-for="(g, i) in preview.groups" :key="i">
          <span class="badge blue">{{ g.cls }}</span>
          <span class="muted small">{{ g.folders.length }} 个文件夹 · {{ g.docs }} 份文档</span>
          <span class="spacer"></span>
          <span class="mono ellip" :title="g.out_dir">{{ g.out_dir }}</span>
        </li>
      </ul>
    </section>

    <section v-if="running || task.logs.length" class="card">
      <div class="card-head">
        <h2>合并进度</h2>
        <span class="muted" v-if="task.jobId">任务 {{ task.jobId }}</span>
      </div>
      <ProgressBar :percent="task.percent" :label="running ? '正在合并' : '合并进度'" :stage="task.stage" />
      <div class="muted msg">{{ task.message }}</div>
      <LogPanel :logs="task.logs" />
    </section>

    <section v-if="result" class="card">
      <div class="card-head"><h2>合并结果</h2><span class="badge green">已完成</span></div>
      <div class="kv">
        <div class="item"><span class="k">合并份数</span><span class="v">{{ result.merged }}</span></div>
        <div class="item"><span class="k">复制份数</span><span class="v">{{ result.copied }}</span></div>
        <div class="item"><span class="k">班级文件夹</span><span class="v">{{ (result.outs || []).length }} 个</span></div>
      </div>
      <div v-if="result.root" class="muted small rootline">
        输出根目录：<span class="mono">{{ result.root }}</span>
      </div>
      <ul class="outs">
        <li v-for="(o, i) in result.outs || []" :key="i">
          <span class="mono ellip" :title="o">{{ o }}</span>
          <button class="btn mini" @click="openFolder(o)">打开文件夹</button>
        </li>
      </ul>
    </section>

    <section v-if="task.error" class="card">
      <div class="card-head"><h2>合并失败</h2><span class="badge orange">错误</span></div>
      <div class="banner error"><div>{{ task.error }}</div></div>
    </section>
  </div>
</template>

<style scoped>
.folderlist,
.outs {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.folderlist li,
.outs li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background: var(--c-surface-2);
}
.tip {
  color: var(--c-text-3);
  font-weight: 400;
}
.rootline {
  margin: 6px 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.groups {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.groups li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  background: var(--c-surface-2);
}
.ellip {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.actions {
  margin-top: 14px;
}
.msg {
  margin: 8px 0;
}
</style>
