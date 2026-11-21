<script setup lang="ts">
/**
 * 外部文件：游戏目录之外的 .usm（拷出来的、网盘下载的）。
 * 添加（拖入 / 选择 / 粘贴路径）→ 自动识别（md5 反查原始路径与密钥）→ 按游戏分任务导出。
 */
import { computed, onMounted, ref, watch } from 'vue'
import {
  FileInput, FolderOpen, FilePlus2, Trash2, CheckCircle2, XCircle, Loader2, Download,
  AlertTriangle, X, Upload, ScanSearch,
} from 'lucide-vue-next'
import {
  api, GAME_IDS, GAME_META, humanSize, methodLabel, methodTone, native, fileName, whenNativeReady,
  type GameId, type IdentifyResult,
} from '../api'
import { staged, stagePaths } from '../store'
import { toast, toastError } from '../toast'
import GameMark from '../components/GameMark.vue'
import ExportDialog from '../components/ExportDialog.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiBadge from '../components/ui/UiBadge.vue'

const hasNative = ref(native.available())
onMounted(async () => { hasNative.value = await whenNativeReady() })

const pathInput = ref('')
const adding = ref(false)
const results = ref<Record<string, IdentifyResult>>({})
const identifying = ref(false)
const exportOpen = ref(false)

/* ---------------- 添加 ---------------- */
async function addPaths(paths: string[]) {
  if (!paths.length) return
  adding.value = true
  try {
    const { files } = await api.expand(paths)
    if (!files.length) { toast('没有找到 .usm 文件', 'info'); return }
    const before = staged.paths.length
    stagePaths(files)
    const added = staged.paths.length - before
    toast(added ? `已添加 ${added} 个文件` : '这些文件已在列表中', added ? 'ok' : 'info')
  } catch (e) { toastError(e, '添加失败') } finally { adding.value = false }
}

async function pickFiles() { addPaths(await native.pickUsmFiles()) }
async function pickFolder() { const d = await native.pickDirectory(); if (d) addPaths([d]) }
function addTyped() {
  const lines = pathInput.value.split(/\r?\n/).map(s => s.trim().replace(/^"|"$/g, '')).filter(Boolean)
  if (!lines.length) return
  addPaths(lines).then(() => { pathInput.value = '' })
}

function removePath(p: string) {
  staged.paths = staged.paths.filter(x => x !== p)
  delete results.value[p]
}
function clearAll() { staged.paths = []; results.value = {} }

/* ---------------- 自动识别（新加入的文件） ---------------- */
let idSeq = 0
watch(() => staged.paths.slice(), async (paths) => {
  const todo = paths.filter(p => !results.value[p])
  if (!todo.length) return
  const my = ++idSeq
  identifying.value = true
  try {
    // 分批识别，大批量时列表逐步出结果
    for (let i = 0; i < todo.length; i += 20) {
      const r = await api.identify(todo.slice(i, i + 20))
      for (const x of r.results) results.value[x.path] = x
      if (my !== idSeq) return
    }
  } catch (e) { toastError(e, '识别失败') } finally { if (my === idSeq) identifying.value = false }
}, { immediate: true })

/* ---------------- 汇总 ---------------- */
const rows = computed(() => staged.paths.map(p => ({ path: p, r: results.value[p] })))
const okRows = computed(() => rows.value.filter(x => x.r && !x.r.error && x.r.game && x.r.method))
const badRows = computed(() => rows.value.filter(x => x.r && (x.r.error || !x.r.method)))
const pending = computed(() => rows.value.filter(x => !x.r).length)

const byGame = computed(() => {
  const m: Partial<Record<GameId, IdentifyResult[]>> = {}
  for (const x of okRows.value) (m[x.r!.game!] ??= []).push(x.r!)
  return m
})
const exportRequests = computed(() =>
  (Object.entries(byGame.value) as [GameId, IdentifyResult[]][]).map(([g, list]) => ({ game: g, paths: list.map(x => x.path) })))
const exportBytes = computed(() => okRows.value.reduce((s, x) => s + (x.r!.size ?? 0), 0))
const exportHasAudio = computed(() => Object.keys(byGame.value).some(g => g !== 'zzz'))

const viaText: Record<string, string> = { path: '路径匹配', name: '文件名匹配', versions: '版本归档' }
function sourceText(r: IdentifyResult) {
  if (r.source === 'external(md5)') return '已按内容找回原始路径'
  if (r.source === 'external') return '按文件名匹配'
  return '位于游戏目录内'
}
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="px-8 pt-7 pb-5 flex items-end gap-4">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">外部文件</h1>
        <p class="mt-1 text-sm text-fg-3">导出不在游戏目录里的 .usm。会根据文件内容自动识别游戏、原始路径和密钥。</p>
      </div>
      <div v-if="staged.paths.length" class="ml-auto flex gap-2">
        <UiButton variant="ghost" :icon="Trash2" @click="clearAll">清空</UiButton>
        <UiButton variant="primary" :icon="Download" :disabled="!okRows.length || identifying" @click="exportOpen = true">
          导出 {{ okRows.length }} 个
        </UiButton>
      </div>
    </header>

    <div class="flex-1 min-h-0 overflow-auto px-8 pb-7 space-y-4">
      <!-- 添加区 -->
      <section
        class="rounded-2xl border-2 border-dashed border-line-strong bg-panel/60 transition-colors"
        :class="staged.paths.length ? 'p-4' : 'p-10'"
      >
        <div v-if="!staged.paths.length" class="text-center">
          <div class="mx-auto h-14 w-14 rounded-2xl bg-accent/12 flex items-center justify-center">
            <Upload class="w-7 h-7 text-accent" />
          </div>
          <p class="mt-4 font-medium">{{ hasNative ? '把 .usm 文件或文件夹拖到窗口里' : '粘贴 .usm 文件或文件夹的路径' }}</p>
          <p class="mt-1 text-sm text-fg-3">文件夹会递归查找其中所有 .usm</p>
          <div v-if="hasNative" class="mt-5 flex justify-center gap-2">
            <UiButton variant="primary" :icon="FilePlus2" @click="pickFiles">选择文件</UiButton>
            <UiButton :icon="FolderOpen" @click="pickFolder">选择文件夹</UiButton>
          </div>
        </div>
        <div v-else-if="hasNative" class="flex items-center gap-2">
          <FileInput class="w-4 h-4 text-fg-3 ml-1" />
          <span class="text-sm text-fg-3">继续拖入，或</span>
          <UiButton size="sm" :icon="FilePlus2" @click="pickFiles">选择文件</UiButton>
          <UiButton size="sm" :icon="FolderOpen" @click="pickFolder">选择文件夹</UiButton>
        </div>

        <div class="flex gap-2" :class="staged.paths.length ? (hasNative ? 'mt-3' : '') : 'mt-6 max-w-2xl mx-auto'">
          <input
            v-model="pathInput" class="input font-mono text-[13px]" spellcheck="false"
            placeholder="粘贴路径，例如 D:\Downloads\cutscenes"
            @keyup.enter="addTyped"
          >
          <UiButton :icon="ScanSearch" :loading="adding" :disabled="!pathInput.trim()" @click="addTyped">添加</UiButton>
        </div>
      </section>

      <!-- 汇总 -->
      <section v-if="staged.paths.length" class="grid grid-cols-4 gap-3">
        <div class="card px-4 py-3">
          <p class="text-xs text-fg-3">已添加</p>
          <p class="mt-1 text-xl font-semibold tabular">{{ staged.paths.length }}</p>
        </div>
        <div class="card px-4 py-3">
          <p class="text-xs text-fg-3">可导出</p>
          <p class="mt-1 text-xl font-semibold tabular text-ok">{{ okRows.length }}</p>
        </div>
        <div class="card px-4 py-3">
          <p class="text-xs text-fg-3">无法导出</p>
          <p class="mt-1 text-xl font-semibold tabular" :class="badRows.length ? 'text-err' : ''">{{ badRows.length }}</p>
        </div>
        <div class="card px-4 py-3">
          <p class="text-xs text-fg-3">游戏</p>
          <div class="mt-1.5 flex items-center gap-1.5 h-7">
            <template v-for="g in GAME_IDS" :key="g">
              <span v-if="byGame[g]" class="inline-flex items-center gap-1 text-sm tabular">
                <GameMark :game="g" :size="22" />{{ byGame[g]!.length }}
              </span>
            </template>
            <span v-if="pending" class="text-xs text-fg-3 flex items-center gap-1"><Loader2 class="w-3.5 h-3.5 animate-spin" />识别中 {{ pending }}</span>
          </div>
        </div>
      </section>

      <!-- 文件列表 -->
      <section v-if="staged.paths.length" class="card overflow-hidden">
        <div
          v-for="x in rows" :key="x.path"
          class="group px-4 py-3 flex items-center gap-3 border-b border-line last:border-0 hover:bg-panel-2/50"
        >
          <Loader2 v-if="!x.r" class="w-[18px] h-[18px] text-fg-3 animate-spin shrink-0" />
          <XCircle v-else-if="x.r.error || !x.r.method" class="w-[18px] h-[18px] text-err shrink-0" />
          <CheckCircle2 v-else class="w-[18px] h-[18px] text-ok shrink-0" />
          <GameMark v-if="x.r?.game" :game="x.r.game" :size="26" />
          <div v-else class="w-[26px] h-[26px] rounded-lg bg-panel-2 shrink-0" />

          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium truncate" :title="x.path">{{ fileName(x.path) }}</p>
            <p class="text-xs truncate" :class="x.r?.error ? 'text-err' : 'text-fg-3'" :title="x.r?.rel_video ?? x.path">
              <template v-if="!x.r">正在识别…</template>
              <template v-else-if="x.r.error">{{ x.r.error }}</template>
              <template v-else-if="!x.r.method">没有找到这个文件的密钥</template>
              <template v-else>{{ sourceText(x.r) }}<template v-if="x.r.source === 'external(md5)'"> · {{ x.r.rel_video }}</template></template>
            </p>
          </div>

          <template v-if="x.r && !x.r.error">
            <span v-if="x.r.via" class="text-xs text-fg-3 shrink-0">{{ viaText[x.r.via] ?? x.r.via }}</span>
            <UiBadge :tone="methodTone(x.r.method)" dot class="shrink-0">{{ methodLabel(x.r.method) }}</UiBadge>
          </template>
          <span class="w-16 text-right text-xs text-fg-3 tabular shrink-0">{{ humanSize(x.r?.size) }}</span>
          <button class="h-7 w-7 rounded-lg flex items-center justify-center text-fg-3 hover:text-fg hover:bg-panel-2 opacity-0 group-hover:opacity-100 shrink-0" title="移除" @click="removePath(x.path)">
            <X class="w-4 h-4" />
          </button>
        </div>
      </section>

      <p v-if="badRows.length" class="flex gap-2 text-xs text-fg-3 leading-5">
        <AlertTriangle class="w-4 h-4 text-warn shrink-0" />
        个别文件在游戏里有同名但密钥不同的版本，离开游戏目录后只能按内容识别。如果识别失败，可以把文件放回游戏原目录，在「游戏文件」页导出。
      </p>
    </div>

    <ExportDialog
      v-model:open="exportOpen" :request="exportRequests" :count="okRows.length" :bytes="exportBytes"
      :has-audio="exportHasAudio"
      :title="exportRequests.length > 1 ? `导出（${exportRequests.length} 个游戏，分别建任务）` : '导出外部文件'"
    />
  </div>
</template>
