<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  FolderOpen, XCircle, CheckCircle2, Ban, Clock, Loader2, Trash2, FileText, ChevronRight,
  ListChecks, Clapperboard, Wand2, CircleSlash, Play,
} from 'lucide-vue-next'
import {
  api, GAME_IDS, GAME_META, LANG_LABEL, fileName, humanDuration, humanSize, relTime,
  type GameId, type TaskResult, type TaskSummary,
} from '../api'
import { activeTask, queuedTasks, refreshTasks, tasks } from '../store'
import { toast, toastError } from '../toast'
import GameMark from '../components/GameMark.vue'
import ExportDialog from '../components/ExportDialog.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiProgress from '../components/ui/UiProgress.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'
import UiDialog from '../components/ui/UiDialog.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import UiSegmented from '../components/ui/UiSegmented.vue'

const router = useRouter()
const finished = computed(() => tasks.value.filter(t => !['running', 'queued'].includes(t.status)))

/* ---------------- 运行中任务：最近完成的文件流 ---------------- */
const feed = ref<{ rel: string, status: string }[]>([])
let feedTask = ''
let feedIdx = 0
let feedTimer: number | undefined

async function pullFeed() {
  const t = activeTask.value
  if (!t) return
  if (t.id !== feedTask) { feedTask = t.id; feedIdx = 0; feed.value = [] }
  try {
    const r = await (await fetch(`/api/tasks/${t.id}/events?after=${feedIdx}`)).json()
    feedIdx = r.index
    for (const e of r.events) if (e.type === 'progress') feed.value.unshift({ rel: e.rel, status: e.status })
    if (feed.value.length > 60) feed.value.length = 60
  } catch { /* 忽略 */ }
}
onMounted(() => { pullFeed(); feedTimer = window.setInterval(pullFeed, 800) })
onUnmounted(() => window.clearInterval(feedTimer))

const now = ref(Date.now() / 1000)
const clock = window.setInterval(() => { now.value = Date.now() / 1000 }, 1000)
onUnmounted(() => window.clearInterval(clock))

const eta = computed(() => {
  const t = activeTask.value
  if (!t?.started || !t.done) return null
  const elapsed = now.value - t.started
  return { elapsed, remain: elapsed / t.done * (t.total - t.done) }
})

async function cancel(t: TaskSummary) {
  try {
    await api.cancelTask(t.id)
    toast(t.status === 'queued' ? '已从队列移除' : '正在取消：当前文件处理完后停止', 'info')
    refreshTasks()
  } catch (e) { toastError(e) }
}

/* ---------------- 历史：展开查看逐文件结果 ---------------- */
const expanded = ref<string | null>(null)
const results = ref<TaskResult[]>([])
const resultsLoading = ref(false)
const resultFilter = ref<'all' | 'fail' | 'skip' | 'ok'>('all')

async function toggleExpand(t: TaskSummary) {
  if (expanded.value === t.id) { expanded.value = null; return }
  expanded.value = t.id
  resultsLoading.value = true
  results.value = []
  try {
    const r = await api.task(t.id)
    results.value = r.results
    resultFilter.value = t.fail ? 'fail' : 'all'
  } catch (e) { toastError(e) } finally { resultsLoading.value = false }
}
const shownResults = computed(() => resultFilter.value === 'all' ? results.value : results.value.filter(r => r.status === resultFilter.value))

async function remove(t: TaskSummary) {
  try { await api.deleteTask(t.id); if (expanded.value === t.id) expanded.value = null; refreshTasks() } catch (e) { toastError(e) }
}
async function clearAll() {
  try { const r = await api.clearTasks(); toast(`已清除 ${r.removed} 条记录（导出的文件不受影响）`, 'ok'); refreshTasks() } catch (e) { toastError(e) }
}

function optsText(t: TaskSummary) {
  const o = t.options
  if (!o) return ''
  const parts: string[] = []
  if (GAME_META[t.game as GameId] && t.game !== 'zzz') {
    parts.push(o.audio === 'all' ? '全部语言' : o.audio === 'none' ? '无音频' : `仅${LANG_LABEL[o.audio] ?? o.audio}`)
    if (o.audio !== 'none') parts.push(o.audio_format.toUpperCase())
  }
  parts.push(o.container === 'auto' ? '自动封装' : o.container.toUpperCase())
  if (o.verify) parts.push('校验')
  return parts.join(' · ')
}

function duration(t: TaskSummary) {
  return t.started && t.finished ? humanDuration(t.finished - t.started) : ''
}

/* ---------------- 按规则批量导出 ---------------- */
const ruleOpen = ref(false)
const ruleExportOpen = ref(false)
const rule = ref({ game: 'gi' as GameId, version: '__latest', scope: 'new' as 'new' | 'modified' | 'changed' | 'all', filter: '' })
const ruleVersions = ref<string[]>([])
const rulePreview = ref<{ count: number, bytes: number } | null>(null)
const rulePreviewing = ref(false)

watch(() => rule.value.game, async (g) => {
  try { ruleVersions.value = (await api.versions(g)).versions } catch { ruleVersions.value = [] }
}, { immediate: true })

const ruleVersionOptions = computed(() => [
  { value: '__latest', label: '最新版本', hint: ruleVersions.value[0] },
  ...ruleVersions.value.map(v => ({ value: v, label: v })),
])
const ruleRequest = computed(() => {
  const r = rule.value
  const all = r.scope === 'all'
  return {
    game: r.game,
    mode: all ? 'all' : r.scope,
    version: all ? undefined : (r.version === '__latest' ? ruleVersions.value[0] : r.version),
    filter: r.filter.trim() || undefined,
  }
})

let previewSeq = 0
watch([rule, ruleVersions], async () => {
  if (!ruleOpen.value) return
  const my = ++previewSeq
  rulePreviewing.value = true
  try {
    const q = ruleRequest.value
    const r = await api.files({ game: q.game, mode: q.mode, version: q.version, filter: q.filter })
    if (my === previewSeq) rulePreview.value = { count: r.targets.length, bytes: r.targets.reduce((s, t) => s + t.size, 0) }
  } catch {
    if (my === previewSeq) rulePreview.value = null
  } finally { if (my === previewSeq) rulePreviewing.value = false }
}, { deep: true })
watch(ruleOpen, (v) => { if (v) rule.value = { ...rule.value } })

function ruleNext() {
  ruleOpen.value = false
  ruleExportOpen.value = true
}

const statusIcon = { done: CheckCircle2, failed: XCircle, cancelled: Ban } as Record<string, any>
</script>

<template>
  <div class="h-full overflow-auto">
    <div class="max-w-[1080px] mx-auto px-8 py-7 space-y-6">
      <header class="flex items-end gap-4">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">导出任务</h1>
          <p class="mt-1 text-sm text-fg-3">任务按顺序逐个执行；关闭窗口会中断正在进行的导出。</p>
        </div>
        <div class="ml-auto flex gap-2">
          <UiButton :icon="Wand2" @click="ruleOpen = true">按版本批量导出</UiButton>
          <UiButton variant="primary" :icon="Clapperboard" @click="router.push('/files')">选择文件导出</UiButton>
        </div>
      </header>

      <!-- 运行中 -->
      <section v-if="activeTask" class="card overflow-hidden">
        <div class="p-5">
          <div class="flex items-center gap-3">
            <GameMark :game="activeTask.game" :size="36" />
            <div class="min-w-0">
              <p class="font-semibold flex items-center gap-2">
                正在导出{{ GAME_META[activeTask.game as GameId]?.title }}
                <Loader2 class="w-4 h-4 animate-spin text-accent" />
              </p>
              <p class="text-xs text-fg-3">{{ optsText(activeTask) }}</p>
            </div>
            <div class="ml-auto flex gap-2">
              <UiButton size="sm" :icon="FolderOpen" @click="api.openFolder(activeTask.out_dir)">输出文件夹</UiButton>
              <UiButton size="sm" variant="danger" :icon="XCircle" @click="cancel(activeTask)">取消</UiButton>
            </div>
          </div>

          <div class="mt-5 flex items-end gap-3">
            <span class="text-3xl font-semibold tabular tracking-tight">{{ Math.floor(activeTask.done / Math.max(1, activeTask.total) * 100) }}%</span>
            <span class="pb-1 text-sm text-fg-3 tabular">{{ activeTask.done }} / {{ activeTask.total }}</span>
            <span v-if="eta" class="ml-auto pb-1 text-xs text-fg-3 tabular">
              已用 {{ humanDuration(eta.elapsed) }} · 预计还需 {{ humanDuration(eta.remain) }}
            </span>
          </div>
          <UiProgress class="mt-2.5" :value="activeTask.done" :max="activeTask.total" animated :height="8" />
          <div class="mt-3 flex gap-4 text-xs">
            <span class="flex items-center gap-1.5 text-ok"><CheckCircle2 class="w-3.5 h-3.5" />成功 {{ activeTask.ok }}</span>
            <span class="flex items-center gap-1.5 text-fg-3"><CircleSlash class="w-3.5 h-3.5" />跳过 {{ activeTask.skip }}</span>
            <span class="flex items-center gap-1.5" :class="activeTask.fail ? 'text-err' : 'text-fg-3'"><XCircle class="w-3.5 h-3.5" />失败 {{ activeTask.fail }}</span>
          </div>
        </div>
        <div class="border-t border-line bg-panel-2/60 px-5 py-3 max-h-56 overflow-auto font-mono text-xs space-y-1">
          <div v-for="c in activeTask.current" :key="'c' + c" class="flex items-center gap-2 text-fg">
            <Loader2 class="w-3.5 h-3.5 animate-spin text-accent shrink-0" />
            <span class="truncate">{{ c }}</span>
          </div>
          <div v-for="(e, i) in feed" :key="i" class="flex items-center gap-2 text-fg-3">
            <CheckCircle2 v-if="e.status === 'ok'" class="w-3.5 h-3.5 text-ok shrink-0" />
            <XCircle v-else-if="e.status === 'fail'" class="w-3.5 h-3.5 text-err shrink-0" />
            <CircleSlash v-else class="w-3.5 h-3.5 shrink-0" />
            <span class="truncate">{{ e.rel }}</span>
          </div>
        </div>
      </section>

      <!-- 排队 -->
      <section v-if="queuedTasks.length" class="card divide-y divide-line">
        <div class="px-5 py-3 text-sm font-semibold">等待中 <span class="text-fg-3 font-normal tabular">{{ queuedTasks.length }}</span></div>
        <div v-for="t in queuedTasks" :key="t.id" class="px-5 py-3 flex items-center gap-3 text-sm">
          <Clock class="w-4 h-4 text-fg-3" />
          <GameMark :game="t.game" :size="22" />
          <span>{{ GAME_META[t.game as GameId]?.title }} · {{ t.total }} 个文件</span>
          <span class="text-xs text-fg-3">{{ optsText(t) }}</span>
          <UiButton class="ml-auto" size="sm" variant="ghost" :icon="XCircle" @click="cancel(t)">移除</UiButton>
        </div>
      </section>

      <!-- 历史 -->
      <section class="card">
        <div class="px-5 py-3.5 flex items-center border-b border-line">
          <h2 class="text-sm font-semibold">历史记录</h2>
          <UiButton v-if="finished.length" class="ml-auto" size="sm" variant="ghost" :icon="Trash2" @click="clearAll">清空记录</UiButton>
        </div>
        <UiEmpty v-if="!finished.length && !activeTask" :icon="ListChecks" title="还没有导出任务" text="在「游戏文件」页勾选文件，或用「按版本批量导出」一次导出某个版本的全部新增动画">
          <UiButton size="sm" variant="subtle" :icon="Clapperboard" @click="router.push('/files')">去选择文件</UiButton>
        </UiEmpty>
        <p v-else-if="!finished.length" class="px-5 py-6 text-sm text-fg-3 text-center">暂无已完成的任务</p>

        <div v-for="t in finished" :key="t.id" class="border-b border-line last:border-0">
          <div class="px-5 py-3.5 flex items-center gap-3 hover:bg-panel-2/50 cursor-pointer" @click="toggleExpand(t)">
            <ChevronRight class="w-4 h-4 text-fg-3 transition-transform" :class="expanded === t.id && 'rotate-90'" />
            <component :is="statusIcon[t.status]" class="w-[18px] h-[18px]"
              :class="t.status === 'done' ? (t.fail ? 'text-warn' : 'text-ok') : t.status === 'failed' ? 'text-err' : 'text-fg-3'" />
            <GameMark :game="t.game" :size="24" />
            <div class="min-w-0">
              <p class="text-sm font-medium">
                {{ GAME_META[t.game as GameId]?.title ?? t.game }} · {{ t.total }} 个文件
                <span v-if="t.status === 'cancelled'" class="text-fg-3 font-normal">（已取消）</span>
              </p>
              <p class="text-xs text-fg-3 truncate">{{ optsText(t) }}<template v-if="duration(t)"> · 用时 {{ duration(t) }}</template></p>
            </div>
            <div class="ml-auto flex items-center gap-1.5 shrink-0">
              <UiBadge v-if="t.ok" tone="ok">成功 {{ t.ok }}</UiBadge>
              <UiBadge v-if="t.skip" tone="neutral">跳过 {{ t.skip }}</UiBadge>
              <UiBadge v-if="t.fail" tone="err">失败 {{ t.fail }}</UiBadge>
              <span class="w-24 text-right text-xs text-fg-3">{{ relTime(t.created) }}</span>
              <UiButton size="icon-sm" variant="ghost" :icon="FolderOpen" title="打开输出文件夹" @click.stop="api.openFolder(t.out_dir)" />
              <UiButton v-if="t.report_path" size="icon-sm" variant="ghost" :icon="FileText" title="打开导出报告" @click.stop="api.openFile(t.report_path)" />
              <UiButton size="icon-sm" variant="ghost" :icon="Trash2" title="删除记录" @click.stop="remove(t)" />
            </div>
          </div>

          <!-- 逐文件结果 -->
          <div v-if="expanded === t.id" class="px-5 pb-4 pl-[52px]">
            <p v-if="t.error" class="mb-3 rounded-lg bg-err/[.07] border border-err/25 px-3 py-2 text-xs text-err selectable">{{ t.error }}</p>
            <div class="flex items-center gap-3 mb-2">
              <UiSegmented v-model="resultFilter" size="sm" :options="[
                { value: 'all', label: `全部 ${results.length}` },
                { value: 'ok', label: `成功 ${t.ok}` },
                { value: 'skip', label: `跳过 ${t.skip}` },
                { value: 'fail', label: `失败 ${t.fail}` },
              ]" />
              <span class="text-xs text-fg-3 truncate font-mono" :title="t.out_dir">{{ t.out_dir }}</span>
            </div>
            <div class="rounded-xl border border-line max-h-80 overflow-auto">
              <div v-if="resultsLoading" class="p-4 text-xs text-fg-3 flex items-center gap-2"><Loader2 class="w-3.5 h-3.5 animate-spin" />读取中…</div>
              <p v-else-if="!results.length" class="p-4 text-xs text-fg-3">该任务没有保存逐文件结果（旧版本创建的任务）。可打开导出报告查看。</p>
              <p v-else-if="!shownResults.length" class="p-4 text-xs text-fg-3">没有这类结果</p>
              <div v-for="r in shownResults" :key="r.rel" class="px-3 py-2 flex items-start gap-2.5 border-b border-line last:border-0 text-xs">
                <CheckCircle2 v-if="r.status === 'ok'" class="w-3.5 h-3.5 mt-0.5 text-ok shrink-0" />
                <XCircle v-else-if="r.status === 'fail'" class="w-3.5 h-3.5 mt-0.5 text-err shrink-0" />
                <CircleSlash v-else class="w-3.5 h-3.5 mt-0.5 text-fg-3 shrink-0" />
                <div class="flex-1 min-w-0">
                  <p class="truncate font-medium" :title="r.rel">{{ fileName(r.rel) }}</p>
                  <p v-if="r.msg && r.status !== 'ok'" class="mt-0.5 text-fg-3 break-all selectable" :class="r.status === 'fail' && 'text-err'">{{ r.msg }}</p>
                  <p v-for="n in r.notes" :key="n" class="mt-0.5 text-fg-3">{{ n }}</p>
                </div>
                <span class="text-fg-3 tabular shrink-0">{{ humanSize(r.size) }}</span>
                <span v-if="r.seconds" class="w-12 text-right text-fg-3 tabular shrink-0">{{ r.seconds.toFixed(1) }}s</span>
                <button v-if="r.output" class="text-accent hover:underline shrink-0 flex items-center gap-1" @click="api.openFile(r.output)">
                  <Play class="w-3 h-3" />播放
                </button>
                <button v-if="r.output" class="text-fg-3 hover:text-fg shrink-0" title="在文件夹中显示" @click="api.openFolder(r.output, true)">
                  <FolderOpen class="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 按规则批量导出：第一步选范围 -->
    <UiDialog v-model:open="ruleOpen" title="按版本批量导出" description="不用逐个勾选，直接导出某个版本新增或更新的全部过场动画" width="560px">
      <div class="space-y-5 py-1">
        <div>
          <p class="text-sm font-medium mb-2">游戏</p>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="g in GAME_IDS" :key="g"
              class="h-12 rounded-xl border flex items-center gap-2.5 px-3 text-sm font-medium transition-colors"
              :class="rule.game === g ? 'border-accent bg-accent/[.07]' : 'border-line hover:border-line-strong'"
              @click="rule.game = g"
            >
              <GameMark :game="g" :size="26" />{{ GAME_META[g].title }}
            </button>
          </div>
        </div>
        <div>
          <p class="text-sm font-medium mb-2">范围</p>
          <UiSegmented v-model="rule.scope" block :options="[
            { value: 'new', label: '新增' }, { value: 'modified', label: '更新' },
            { value: 'changed', label: '新增 + 更新' }, { value: 'all', label: '全部文件' },
          ]" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <p class="text-sm font-medium mb-2">版本</p>
            <UiSelect v-model="rule.version" :options="ruleVersionOptions" :disabled="rule.scope === 'all'" class="w-full" />
          </div>
          <div>
            <p class="text-sm font-medium mb-2">文件名匹配 <span class="text-fg-3 font-normal">（可选）</span></p>
            <input v-model="rule.filter" class="input font-mono text-[13px]" placeholder="例如 *Act210*" spellcheck="false">
          </div>
        </div>
        <div class="rounded-xl bg-panel-2 px-4 py-3 text-sm flex items-center gap-2">
          <Loader2 v-if="rulePreviewing" class="w-4 h-4 animate-spin text-fg-3" />
          <template v-else-if="rulePreview">
            将导出 <span class="font-semibold tabular">{{ rulePreview.count }}</span> 个文件
            <span class="text-fg-3">· {{ humanSize(rulePreview.bytes) }}</span>
          </template>
          <span v-else class="text-fg-3">无法预览：请确认游戏目录已设置</span>
        </div>
      </div>
      <template #footer>
        <div class="ml-auto flex gap-2">
          <UiButton variant="ghost" @click="ruleOpen = false">取消</UiButton>
          <UiButton variant="primary" :disabled="!rulePreview?.count" @click="ruleNext">下一步</UiButton>
        </div>
      </template>
    </UiDialog>

    <ExportDialog
      v-model:open="ruleExportOpen" :request="ruleRequest" :count="rulePreview?.count ?? 0" :bytes="rulePreview?.bytes"
      :has-audio="rule.game !== 'zzz'" :title="`导出${GAME_META[rule.game].title}过场动画`"
    />
  </div>
</template>
