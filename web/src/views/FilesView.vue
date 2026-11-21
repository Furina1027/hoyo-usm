<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVirtualizer } from '@tanstack/vue-virtual'
import {
  Search, Download, RefreshCw, ArrowUp, ArrowDown, ChevronsUpDown, X, FolderOpen,
  SearchX, Settings2, Layers, Tag,
} from 'lucide-vue-next'
import {
  api, GAME_IDS, GAME_META, humanSize, methodLabel, methodTone, fileName, dirName,
  type FilesReport, type GameId, type Target,
} from '../api'
import { toastError } from '../toast'
import GameMark from '../components/GameMark.vue'
import ProbeDrawer from '../components/ProbeDrawer.vue'
import ExportDialog from '../components/ExportDialog.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiCheckbox from '../components/ui/UiCheckbox.vue'
import UiSelect from '../components/ui/UiSelect.vue'
import UiSegmented from '../components/ui/UiSegmented.vue'
import UiEmpty from '../components/ui/UiEmpty.vue'

const route = useRoute()
const router = useRouter()

const game = ref<GameId>((GAME_IDS as string[]).includes(String(route.query.game)) ? route.query.game as GameId : 'gi')
const version = ref<string>(String(route.query.version ?? '__all'))
const scope = ref<'new' | 'modified' | 'changed'>('new')
const query = ref('')
const methodFilter = ref<string>('__all')
const loading = ref(false)
const error = ref('')
const report = ref<FilesReport | null>(null)
const selected = ref<Set<string>>(new Set())
const probe = ref<Target | null>(null)
const exportOpen = ref(false)
const searchEl = ref<HTMLInputElement | null>(null)

type SortKey = 'name' | 'size' | 'version' | 'method'
const sortKey = ref<SortKey>('name')
const sortDir = ref<1 | -1>(1)

/* ---------------- 加载 ---------------- */
let loadSeq = 0
async function load(refresh = false) {
  const my = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    const v = version.value === '__all' ? '' : version.value
    const r = await api.files({ game: game.value, mode: v ? scope.value : 'all', version: v || undefined, refresh })
    if (my !== loadSeq) return
    report.value = r
    // 保留仍然存在的勾选
    const keep = new Set(r.targets.map(t => t.rel_video))
    selected.value = new Set([...selected.value].filter(k => keep.has(k)))
  } catch (e: any) {
    if (my !== loadSeq) return
    error.value = e.message ?? '加载失败'
    report.value = null
  } finally {
    if (my === loadSeq) loading.value = false
  }
}

watch(game, () => {
  version.value = '__all'
  selected.value = new Set()
  probe.value = null
  router.replace({ query: { game: game.value } })
})
watch([game, version, scope], () => load())
onMounted(() => load())

/* ---------------- 过滤 / 排序（前端，≤ 几千行） ---------------- */
const versionOptions = computed(() => [
  { value: '__all', label: '全部版本' },
  ...(report.value?.versions ?? []).map((v, i) => ({ value: v, label: v, hint: i === 0 ? '最新' : undefined })),
])
const methodOptions = [
  { value: '__all', label: '全部加密' },
  { value: 'mask', label: '旧版加密' },
  { value: 'aes', label: '新版加密' },
  { value: 'plain', label: '未加密' },
  { value: '__missing', label: '缺密钥' },
]

function vkey(v: string | null) {
  return (v ?? '').split('.').map(n => n.padStart(4, '0')).join('.')
}

const rows = computed<Target[]>(() => {
  let list = report.value?.targets ?? []
  const q = query.value.trim().toLowerCase()
  if (q) {
    const parts = q.split(/\s+/)
    list = list.filter(t => { const s = t.rel_video.toLowerCase(); return parts.every(p => s.includes(p)) })
  }
  if (methodFilter.value !== '__all')
    list = list.filter(t => methodFilter.value === '__missing' ? !t.entry_method : t.entry_method === methodFilter.value)
  const k = sortKey.value
  const d = sortDir.value
  const cmp = (a: Target, b: Target): number => {
    switch (k) {
      case 'size': return (a.size - b.size) * d
      case 'version': return vkey(a.version).localeCompare(vkey(b.version)) * d || a.rel_video.localeCompare(b.rel_video)
      case 'method': return (a.entry_method ?? '').localeCompare(b.entry_method ?? '') * d || a.rel_video.localeCompare(b.rel_video)
      default: return fileName(a.rel_video).localeCompare(fileName(b.rel_video), undefined, { numeric: true }) * d
    }
  }
  return [...list].sort(cmp)
})

function sortBy(k: SortKey) {
  if (sortKey.value === k) sortDir.value = sortDir.value === 1 ? -1 : 1
  else { sortKey.value = k; sortDir.value = k === 'size' || k === 'version' ? -1 : 1 }
}

/* ---------------- 选择 ---------------- */
const visibleSelected = computed(() => rows.value.filter(t => selected.value.has(t.rel_video)).length)
const allChecked = computed(() => rows.value.length > 0 && visibleSelected.value === rows.value.length)
const someChecked = computed(() => visibleSelected.value > 0 && !allChecked.value)
const selectedTargets = computed(() => (report.value?.targets ?? []).filter(t => selected.value.has(t.rel_video)))
const selectedBytes = computed(() => selectedTargets.value.reduce((s, t) => s + t.size, 0))
const totalBytes = computed(() => rows.value.reduce((s, t) => s + t.size, 0))

let anchor = -1
function toggleRow(index: number, e?: MouseEvent) {
  const s = new Set(selected.value)
  const t = rows.value[index]
  if (e?.shiftKey && anchor >= 0) {
    const [a, b] = anchor < index ? [anchor, index] : [index, anchor]
    for (let i = a; i <= b; i++) s.add(rows.value[i].rel_video)
  } else {
    s.has(t.rel_video) ? s.delete(t.rel_video) : s.add(t.rel_video)
    anchor = index
  }
  selected.value = s
}
function toggleAll() {
  const s = new Set(selected.value)
  if (allChecked.value) rows.value.forEach(t => s.delete(t.rel_video))
  else rows.value.forEach(t => s.add(t.rel_video))
  selected.value = s
}
function clearSelection() { selected.value = new Set() }

/* ---------------- 虚拟列表 ---------------- */
const scrollEl = ref<HTMLElement | null>(null)
const ROW_H = 44
const virtualizer = useVirtualizer(computed(() => ({
  count: rows.value.length,
  getScrollElement: () => scrollEl.value,
  estimateSize: () => ROW_H,
  overscan: 12,
})))
const vItems = computed(() => virtualizer.value.getVirtualItems())
watch(rows, () => virtualizer.value.scrollToOffset(0))

/* ---------------- 键盘 ---------------- */
const cursor = ref(-1)
function onKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  const inInput = tag === 'INPUT' || tag === 'TEXTAREA'
  if ((e.ctrlKey && e.key === 'f') || (e.key === '/' && !inInput)) {
    e.preventDefault(); searchEl.value?.focus(); searchEl.value?.select(); return
  }
  if (document.querySelector('[role="dialog"]')) return
  if (inInput) {
    if (e.key === 'Escape') { query.value = ''; (e.target as HTMLElement).blur() }
    return
  }
  if (e.ctrlKey && e.key === 'a') { e.preventDefault(); toggleAll(); return }
  if (e.key === 'Escape') { probe.value ? (probe.value = null) : clearSelection(); return }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    const n = rows.value.length
    if (!n) return
    cursor.value = Math.max(0, Math.min(n - 1, cursor.value + (e.key === 'ArrowDown' ? 1 : -1)))
    virtualizer.value.scrollToIndex(cursor.value, { align: 'auto' })
    if (probe.value) probe.value = rows.value[cursor.value]
    return
  }
  if (e.key === ' ' && cursor.value >= 0) { e.preventDefault(); toggleRow(cursor.value); return }
  if (e.key === 'Enter' && cursor.value >= 0) { probe.value = rows.value[cursor.value]; return }
  if (e.ctrlKey && e.key === 'e' && selected.value.size) { e.preventDefault(); openExport(selectedTargets.value) }
}
onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))

function openRow(i: number) {
  cursor.value = i
  probe.value = rows.value[i]
}

/** 导出对象：底部按钮 = 勾选项；抽屉里的「导出此文件」= 单个文件（不改动勾选）。 */
const exportTargets = ref<Target[]>([])
function openExport(list: Target[]) {
  if (!list.length) return
  exportTargets.value = list
  exportOpen.value = true
}
const exportRequest = computed(() => ({ game: game.value, paths: exportTargets.value.map(t => t.path) }))
const exportBytes = computed(() => exportTargets.value.reduce((s, t) => s + t.size, 0))

function clsLabel(c: string | null) {
  return c === 'new' ? '新增' : c === 'modified' ? '更新' : ''
}
</script>

<template>
  <div class="h-full flex">
    <div class="flex-1 min-w-0 flex flex-col">
      <!-- 顶栏：游戏切换 -->
      <header class="px-7 pt-6 pb-4 flex items-center gap-4">
        <h1 class="text-2xl font-semibold tracking-tight">游戏文件</h1>
        <div class="flex gap-1.5 ml-3">
          <button
            v-for="gid in GAME_IDS" :key="gid"
            class="h-9 pl-1.5 pr-3.5 rounded-[11px] flex items-center gap-2 text-sm font-medium border transition-all"
            :class="game === gid ? 'bg-panel border-line-strong text-fg shadow-[0_1px_3px_rgb(0_0_0/.15)]' : 'border-transparent text-fg-3 hover:text-fg-2 hover:bg-panel-2'"
            @click="game = gid"
          >
            <GameMark :game="gid" :size="24" />
            {{ GAME_META[gid].title }}
          </button>
        </div>
        <div class="ml-auto flex gap-2">
          <UiButton v-if="report?.root" variant="ghost" size="icon" :icon="FolderOpen" title="打开游戏目录" @click="api.openFolder(report.root)" />
          <UiButton variant="ghost" size="icon" :icon="RefreshCw" title="重新扫描" :loading="loading" @click="load(true)" />
        </div>
      </header>

      <!-- 工具栏 -->
      <div class="px-7 pb-4 flex items-center gap-2.5">
        <div class="relative w-[300px]">
          <Search class="w-4 h-4 text-fg-3 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            ref="searchEl" v-model="query" placeholder="搜索文件名或路径"
            class="input pl-9 pr-14" spellcheck="false"
          >
          <button v-if="query" class="absolute right-2 top-1/2 -translate-y-1/2 h-6 w-6 rounded-md flex items-center justify-center text-fg-3 hover:text-fg" @click="query = ''">
            <X class="w-3.5 h-3.5" />
          </button>
          <span v-else class="kbd absolute right-2.5 top-1/2 -translate-y-1/2">/</span>
        </div>
        <UiSelect v-model="version" :options="versionOptions" class="w-40" :icon="Tag" />
        <UiSegmented
          v-if="version !== '__all'" v-model="scope" size="sm"
          :options="[{ value: 'new', label: '新增' }, { value: 'modified', label: '更新' }, { value: 'changed', label: '新增+更新' }]"
        />
        <UiSelect v-model="methodFilter" :options="methodOptions" class="w-36" :icon="Layers" />
        <span class="ml-auto text-xs text-fg-3 tabular">{{ rows.length }} 个 · {{ humanSize(totalBytes) }}</span>
      </div>

      <!-- 表格 -->
      <div class="flex-1 min-h-0 mx-7 mb-5 card flex flex-col overflow-hidden">
        <div class="h-10 shrink-0 flex items-center gap-3 px-4 border-b border-line text-xs font-medium text-fg-3">
          <UiCheckbox :checked="allChecked" :indeterminate="someChecked" :disabled="!rows.length" @toggle="toggleAll" />
          <button class="flex-1 flex items-center gap-1 hover:text-fg text-left" @click="sortBy('name')">
            文件
            <component :is="sortKey === 'name' ? (sortDir === 1 ? ArrowUp : ArrowDown) : ChevronsUpDown" class="w-3 h-3" :class="sortKey !== 'name' && 'opacity-40'" />
          </button>
          <button class="w-20 flex items-center gap-1 hover:text-fg" @click="sortBy('version')">
            版本
            <component :is="sortKey === 'version' ? (sortDir === 1 ? ArrowUp : ArrowDown) : ChevronsUpDown" class="w-3 h-3" :class="sortKey !== 'version' && 'opacity-40'" />
          </button>
          <button class="w-24 flex items-center gap-1 hover:text-fg" @click="sortBy('method')">
            加密
            <component :is="sortKey === 'method' ? (sortDir === 1 ? ArrowUp : ArrowDown) : ChevronsUpDown" class="w-3 h-3" :class="sortKey !== 'method' && 'opacity-40'" />
          </button>
          <button class="w-20 flex items-center justify-end gap-1 hover:text-fg" @click="sortBy('size')">
            <component :is="sortKey === 'size' ? (sortDir === 1 ? ArrowUp : ArrowDown) : ChevronsUpDown" class="w-3 h-3" :class="sortKey !== 'size' && 'opacity-40'" />
            大小
          </button>
        </div>

        <div v-if="error" class="flex-1">
          <UiEmpty :icon="Settings2" :title="error" text="确认游戏目录设置正确后重试">
            <UiButton size="sm" variant="subtle" @click="router.push('/settings')">打开设置</UiButton>
            <UiButton size="sm" variant="ghost" @click="load(true)">重试</UiButton>
          </UiEmpty>
        </div>
        <div v-else-if="loading && !report" class="flex-1 p-4 space-y-2">
          <div v-for="i in 10" :key="i" class="h-8 rounded-lg bg-panel-2 animate-pulse" :style="{ opacity: 1 - i * 0.08 }" />
        </div>
        <div v-else-if="!rows.length" class="flex-1">
          <UiEmpty :icon="SearchX" title="没有匹配的文件" :text="query ? `没有文件名包含“${query}”` : '换个版本或筛选条件试试'">
            <UiButton v-if="query || methodFilter !== '__all'" size="sm" variant="subtle" @click="query = ''; methodFilter = '__all'">清除筛选</UiButton>
          </UiEmpty>
        </div>
        <div v-else ref="scrollEl" class="flex-1 min-h-0 overflow-auto" :class="loading && 'opacity-60 transition-opacity'">
          <div class="relative w-full" :style="{ height: `${virtualizer.getTotalSize()}px` }">
            <div
              v-for="v in vItems" :key="rows[v.index].rel_video"
              class="absolute left-0 right-0 flex items-center gap-3 px-4 border-b border-line/60 cursor-default transition-colors"
              :class="[
                probe?.rel_video === rows[v.index].rel_video ? 'bg-accent/10'
                : selected.has(rows[v.index].rel_video) ? 'bg-accent/[.05]' : 'hover:bg-panel-2',
                cursor === v.index && 'ring-1 ring-inset ring-accent/40',
              ]"
              :style="{ height: `${ROW_H}px`, transform: `translateY(${v.start}px)` }"
              @click="openRow(v.index)"
            >
              <UiCheckbox :checked="selected.has(rows[v.index].rel_video)" @toggle="toggleRow(v.index, $event)" />
              <div class="flex-1 min-w-0 flex items-baseline gap-2">
                <span class="truncate text-sm font-medium" :title="rows[v.index].rel_video">{{ fileName(rows[v.index].rel_video) }}</span>
                <span v-if="dirName(rows[v.index].rel_video)" class="truncate text-xs text-fg-3 shrink-[2]">{{ dirName(rows[v.index].rel_video) }}</span>
                <UiBadge v-if="rows[v.index].source === 'hotfix'" tone="neutral" class="shrink-0">热更</UiBadge>
                <UiBadge v-if="clsLabel(rows[v.index].cls)" :tone="rows[v.index].cls === 'new' ? 'ok' : 'accent'" class="shrink-0">{{ clsLabel(rows[v.index].cls) }}</UiBadge>
              </div>
              <span class="w-20 text-xs text-fg-2 tabular">{{ rows[v.index].version ?? '—' }}</span>
              <span class="w-24"><UiBadge :tone="methodTone(rows[v.index].entry_method)" dot>{{ methodLabel(rows[v.index].entry_method) }}</UiBadge></span>
              <span class="w-20 text-right text-xs text-fg-2 tabular">{{ humanSize(rows[v.index].size) }}</span>
            </div>
          </div>
        </div>

        <!-- 底部操作条 -->
        <div class="h-14 shrink-0 flex items-center gap-3 px-4 border-t border-line bg-panel">
          <template v-if="selected.size">
            <span class="text-sm"><span class="font-semibold tabular">{{ selected.size }}</span> 个已选</span>
            <span class="text-xs text-fg-3 tabular">{{ humanSize(selectedBytes) }}</span>
            <button class="text-xs text-fg-3 hover:text-fg" @click="clearSelection">清除</button>
          </template>
          <span v-else class="text-xs text-fg-3">
            点击行查看详情 · 勾选后导出 · <span class="kbd">Shift</span> 连选 · <span class="kbd">↑</span><span class="kbd">↓</span> 浏览
          </span>
          <div class="ml-auto flex gap-2">
            <UiButton v-if="!selected.size && rows.length" variant="ghost" @click="toggleAll">全选 {{ rows.length }} 个</UiButton>
            <UiButton variant="primary" :icon="Download" :disabled="!selected.size" @click="openExport(selectedTargets)">
              导出{{ selected.size ? ` ${selected.size} 个` : '' }}
            </UiButton>
          </div>
        </div>
      </div>
    </div>

    <!-- 详情抽屉 -->
    <Transition name="drawer">
      <ProbeDrawer v-if="probe" :target="probe" :game="game" @close="probe = null"
        @export="openExport([probe!])" />
    </Transition>

    <ExportDialog
      v-model:open="exportOpen" :request="exportRequest" :count="exportTargets.length" :bytes="exportBytes"
      :has-audio="!!report?.has_audio" :title="`导出${GAME_META[game].title}过场动画`"
    />
  </div>
</template>
