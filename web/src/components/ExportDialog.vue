<script setup lang="ts">
/**
 * 导出确认对话框：游戏文件 / 外部文件 / 批量规则三个入口共用。
 * 选项默认取设置里上次用过的值，提交成功后写回设置。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Film, FolderOpen, AudioLines, HardDrive } from 'lucide-vue-next'
import { api, humanSize, native, LANG_LABEL, type ExportParams } from '../api'
import { patchSettings, refreshTasks, settings, activeTask } from '../store'
import { toast, toastError } from '../toast'
import UiDialog from './ui/UiDialog.vue'
import UiButton from './ui/UiButton.vue'
import UiSelect from './ui/UiSelect.vue'
import UiSegmented from './ui/UiSegmented.vue'
import UiSwitch from './ui/UiSwitch.vue'
import UiField from './ui/UiField.vue'

type Req = Omit<ExportParams, 'audio' | 'audio_format' | 'container' | 'verify' | 'jobs'>

const props = defineProps<{
  /** 不含音频选项的请求体（paths 或 mode/version/filter）；数组 = 按游戏拆成多个任务 */
  request: Req | Req[]
  count: number
  bytes?: number
  hasAudio: boolean
  title?: string
}>()
const open = defineModel<boolean>('open', { required: true })
const router = useRouter()

const audio = ref('all')
const audioFormat = ref('flac')
const container = ref('auto')
const verify = ref(true)
const jobs = ref('1')
const outDir = ref('')
const submitting = ref(false)

watch(open, (v) => {
  if (!v || !settings.value) return
  const s = settings.value
  audio.value = s.audio || 'all'
  audioFormat.value = s.audio_format || 'flac'
  container.value = s.container || 'auto'
  verify.value = s.verify ?? true
  jobs.value = String(s.jobs || 1)
  outDir.value = s.out_dir_effective || ''
}, { immediate: true })

const audioOptions = [
  { value: 'all', label: '全部语言', hint: '多音轨' },
  ...Object.entries(LANG_LABEL).map(([v, l]) => ({ value: v, label: `仅${l}` })),
  { value: 'none', label: '不要音频', hint: '纯视频' },
]
const formatOptions = [
  { value: 'flac', label: 'FLAC', hint: '无损 · 推荐' },
  { value: 'wav', label: 'WAV', hint: '无损 · 体积大' },
  { value: 'aac', label: 'AAC', hint: '有损 · 兼容性好' },
  { value: 'raw', label: '原始码流', hint: 'HCA/ADX 单独存放' },
]
const containerOptions = [
  { value: 'auto', label: '自动' },
  { value: 'mkv', label: 'MKV' },
  { value: 'mp4', label: 'MP4' },
  { value: 'webm', label: 'WebM' },
]
const jobOptions = ['1', '2', '3', '4', '6', '8'].map(v => ({ value: v, label: `${v} 个进程` }))

const summary = computed(() => {
  const parts = [`${props.count} 个文件`]
  if (props.bytes) parts.push(humanSize(props.bytes))
  return parts.join(' · ')
})

async function pickOut() {
  const p = await native.pickDirectory(outDir.value)
  if (p) outDir.value = p
}

async function submit() {
  submitting.value = true
  try {
    const opts = {
      audio: props.hasAudio ? audio.value : 'none',
      audio_format: audioFormat.value,
      container: container.value,
      verify: verify.value,
      jobs: Number(jobs.value),
    }
    const reqs = Array.isArray(props.request) ? props.request : [props.request]
    let total = 0
    let out = ''
    let firstId = ''
    for (const req of reqs) {
      const r = await api.export({ ...req, ...opts, out_dir: outDir.value.trim() || undefined })
      total += r.total
      out = r.out_dir
      firstId ||= r.task_id
    }
    // 记住本次选项（音轨只在有音频的游戏里记）
    patchSettings({
      ...(props.hasAudio ? { audio: opts.audio } : {}),
      audio_format: opts.audio_format, container: opts.container, verify: opts.verify, jobs: opts.jobs,
    }).catch(() => {})
    open.value = false
    await refreshTasks()
    toast({
      kind: 'ok',
      title: activeTask.value && activeTask.value.id !== firstId ? `已加入队列：${total} 个文件` : `开始导出 ${total} 个文件`,
      text: reqs.length > 1 ? `${reqs.length} 个任务 · ${out}` : out,
      action: { label: '查看进度', run: () => router.push('/tasks') },
    })
  } catch (e) {
    toastError(e, '无法创建导出任务')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <UiDialog v-model:open="open" :title="title ?? '导出'" :description="summary" width="600px">
    <div class="divide-y divide-line">
      <template v-if="hasAudio">
        <UiField label="音轨" hint="多语言时每种语言一条音轨，并写入语言标签">
          <UiSelect v-model="audio" :options="audioOptions" class="w-44" :icon="AudioLines" />
        </UiField>
        <UiField label="音频格式" :hint="audioFormat === 'raw' ? '视频内不含音轨，音频以原始码流文件存放在旁边' : 'HCA / ADX 解码为 PCM 后封装'">
          <UiSelect v-model="audioFormat" :options="formatOptions" class="w-44" :disabled="audio === 'none'" />
        </UiField>
      </template>
      <div v-else class="py-3.5 text-sm text-fg-3 flex items-center gap-2">
        <Film class="w-4 h-4" /> 绝区零的过场动画不含音频，将导出纯视频。
      </div>
      <UiField label="封装格式" hint="自动：H.264 → MP4，VP9 → WebM / MKV，MPEG-1 → MKV">
        <UiSegmented v-model="container" :options="containerOptions" size="sm" />
      </UiField>
      <UiField label="导出后校验" hint="用 ffmpeg 完整解码一遍，确认无错误帧">
        <UiSwitch v-model="verify" />
      </UiField>
      <UiField label="并行" hint="同时处理的文件数；机械硬盘建议 1–2">
        <UiSelect v-model="jobs" :options="jobOptions" class="w-36" size="sm" />
      </UiField>
      <UiField label="输出到" stacked>
        <div class="flex gap-2">
          <input v-model="outDir" class="input font-mono text-[13px]" spellcheck="false">
          <UiButton v-if="native.available()" :icon="FolderOpen" @click="pickOut">选择</UiButton>
        </div>
      </UiField>
    </div>

    <template #footer>
      <span class="text-xs text-fg-3 flex items-center gap-1.5">
        <HardDrive class="w-3.5 h-3.5" /> 视频流原样复制，不重新编码
      </span>
      <div class="ml-auto flex gap-2">
        <UiButton variant="ghost" @click="open = false">取消</UiButton>
        <UiButton variant="primary" :icon="Film" :loading="submitting" :disabled="!count" @click="submit">
          {{ activeTask ? '加入队列' : '开始导出' }}
        </UiButton>
      </div>
    </template>
  </UiDialog>
</template>
