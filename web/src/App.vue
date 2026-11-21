<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TooltipProvider } from 'reka-ui'
import {
  LayoutDashboard, Clapperboard, ListChecks, FileInput, Settings2, Info,
  Moon, Sun, CheckCircle2, XCircle, Info as InfoIcon, X, Loader2, Upload,
} from 'lucide-vue-next'
import { toasts, dismiss, toast } from './toast'
import {
  activeTask, busyCount, loadEnv, loadSettings, onTaskFinished, patchSettings,
  refreshTasks, settings, stagePaths, staged,
} from './store'
import { api, GAME_IDS, GAME_META, whenNativeReady, type GameId } from './api'
import GameMark from './components/GameMark.vue'
import UiTooltip from './components/ui/UiTooltip.vue'
import UiProgress from './components/ui/UiProgress.vue'

const route = useRoute()
const router = useRouter()
const ready = ref(false)
const isWizard = computed(() => route.name === 'wizard')

const nav = computed(() => [
  { name: 'overview', label: '总览', icon: LayoutDashboard, key: '1' },
  { name: 'files', label: '游戏文件', icon: Clapperboard, key: '2' },
  { name: 'tasks', label: '导出任务', icon: ListChecks, key: '3', badge: busyCount.value || undefined },
  { name: 'external', label: '外部文件', icon: FileInput, key: '4', badge: staged.paths.length || undefined },
  { name: 'settings', label: '设置', icon: Settings2, key: '5' },
])

/* ---------------- 拖放 ---------------- */
const dragOver = ref(false)
let dragDepth = 0
const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files')

function onDragEnter(e: DragEvent) {
  if (!hasFiles(e) || isWizard.value) return
  e.preventDefault()
  dragDepth++
  dragOver.value = true
}
function onDragLeave(e: DragEvent) {
  if (!hasFiles(e)) return
  if (--dragDepth <= 0) { dragDepth = 0; dragOver.value = false }
}
function onDragOver(e: DragEvent) { if (hasFiles(e)) e.preventDefault() }
function onDrop(e: DragEvent) {
  e.preventDefault()
  dragDepth = 0
  dragOver.value = false
  // 窗口模式：真实路径由 pywebview 经 __hoyoNativeDrop 回推；浏览器模式拿不到路径
  if (!(window as any).pywebview) {
    toast({ kind: 'info', title: '浏览器模式无法读取拖入文件的路径', text: '请在「外部文件」页粘贴文件夹路径扫描' })
    router.push('/external')
  }
}

;(window as any).__hoyoNativeDrop = async (paths: string[]) => {
  try {
    const { files } = await api.expand(paths)
    if (!files.length) { toast('拖入的内容里没有 .usm 文件', 'info'); return }
    stagePaths(files)
    toast(`已添加 ${files.length} 个文件`, 'ok')
    if (route.name !== 'external') router.push('/external')
  } catch (e: any) { toast({ kind: 'error', title: '添加失败', text: e.message }) }
}

/* ---------------- 快捷键 ---------------- */
function onKey(e: KeyboardEvent) {
  if (!e.ctrlKey || e.shiftKey || e.altKey) return
  const item = nav.value.find(n => n.key === e.key)
  if (item) { e.preventDefault(); router.push({ name: item.name }) }
}

/* ---------------- 主题 ---------------- */
const isDark = computed(() => settings.value?.theme !== 'light')
function toggleTheme() {
  patchSettings({ theme: isDark.value ? 'light' : 'dark' }).catch(() => {})
}

/* ---------------- 任务完成通知 ---------------- */
const offFinish = onTaskFinished((t) => {
  const title = GAME_META[t.game as GameId]?.title ?? t.game
  if (t.status === 'done') {
    toast({
      kind: t.fail ? 'error' : 'ok',
      title: t.fail ? `${title}导出完成，${t.fail} 个失败` : `${title}导出完成`,
      text: `成功 ${t.ok} · 跳过 ${t.skip} · 失败 ${t.fail}`,
      action: { label: '打开文件夹', run: () => api.openFolder(t.out_dir) },
    })
  } else if (t.status === 'failed') {
    toast({ kind: 'error', title: '导出任务出错', text: t.error })
  }
})

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  try {
    await router.isReady()
    const s = await loadSettings()
    if (!s.wizard_done && route.name !== 'wizard') router.replace('/wizard')
    else if (s.wizard_done && route.name === 'wizard') router.replace('/')
  } catch { /* 后端异常时页面自行兜底 */ }
  ready.value = true
  whenNativeReady()
  refreshTasks()
  loadEnv().catch(() => {})
})
onUnmounted(() => { window.removeEventListener('keydown', onKey); offFinish() })

const version = __APP_VERSION__
</script>

<template>
  <TooltipProvider :delay-duration="350">
    <div
      class="h-full flex"
      @dragenter="onDragEnter" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop"
    >
      <!-- 侧边栏 -->
      <aside v-if="!isWizard" class="w-[220px] shrink-0 flex flex-col bg-panel border-r border-line">
        <div class="h-16 flex items-center gap-2.5 px-5">
          <div class="h-8 w-8 rounded-[10px] bg-gradient-to-br from-accent-2 to-accent flex items-center justify-center shadow-[0_6px_16px_-6px_var(--c-accent)]">
            <Clapperboard class="w-[18px] h-[18px] text-white" />
          </div>
          <div class="leading-tight">
            <div class="font-semibold tracking-tight">hoyo-usm</div>
            <div class="text-[11px] text-fg-3">过场动画无损导出</div>
          </div>
        </div>

        <nav class="flex-1 px-3 py-2 space-y-0.5">
          <RouterLink
            v-for="item in nav" :key="item.name" :to="{ name: item.name }"
            class="group relative h-9 px-3 rounded-[10px] flex items-center gap-3 text-sm transition-colors"
            :class="route.name === item.name
              ? 'bg-accent/12 text-fg font-medium'
              : 'text-fg-2 hover:bg-panel-2 hover:text-fg'"
          >
            <span v-if="route.name === item.name" class="absolute left-0 top-2 bottom-2 w-[3px] rounded-r bg-accent" />
            <component :is="item.icon" class="w-[18px] h-[18px]" :class="route.name === item.name ? 'text-accent' : 'text-fg-3 group-hover:text-fg-2'" />
            <span class="flex-1">{{ item.label }}</span>
            <span v-if="item.badge" class="min-w-5 h-5 px-1.5 rounded-full bg-accent text-white text-[11px] font-semibold flex items-center justify-center tabular">{{ item.badge }}</span>
            <span v-else class="kbd opacity-0 group-hover:opacity-100 transition-opacity">{{ item.key }}</span>
          </RouterLink>
        </nav>

        <!-- 当前任务迷你卡片 -->
        <RouterLink
          v-if="activeTask" to="/tasks"
          class="mx-3 mb-3 p-3 rounded-xl bg-panel-2 border border-line hover:border-line-strong transition-colors"
        >
          <div class="flex items-center gap-2 text-xs">
            <Loader2 class="w-3.5 h-3.5 animate-spin text-accent" />
            <span class="font-medium">正在导出</span>
            <span class="ml-auto text-fg-3 tabular">{{ activeTask.done }}/{{ activeTask.total }}</span>
          </div>
          <UiProgress class="mt-2" :value="activeTask.done" :max="activeTask.total" :height="4" />
        </RouterLink>

        <div class="px-3 pb-3 flex items-center gap-1">
          <RouterLink
            to="/about"
            class="h-8 px-2.5 rounded-lg flex items-center gap-2 text-xs transition-colors"
            :class="route.name === 'about' ? 'text-fg bg-panel-2' : 'text-fg-3 hover:text-fg hover:bg-panel-2'"
          >
            <Info class="w-3.5 h-3.5" /> 关于 · v{{ version }}
          </RouterLink>
          <UiTooltip :text="isDark ? '切换到浅色' : '切换到深色'">
            <button class="ml-auto h-8 w-8 rounded-lg flex items-center justify-center text-fg-3 hover:text-fg hover:bg-panel-2" @click="toggleTheme">
              <Sun v-if="isDark" class="w-4 h-4" />
              <Moon v-else class="w-4 h-4" />
            </button>
          </UiTooltip>
        </div>
      </aside>

      <!-- 主内容 -->
      <main class="flex-1 min-w-0 relative">
        <RouterView v-if="ready" v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>

      <!-- 拖拽覆盖层 -->
      <Transition name="fade">
        <div v-if="dragOver" class="fixed inset-0 z-[95] bg-bg/70 backdrop-blur-sm p-6 pointer-events-none">
          <div class="h-full rounded-3xl border-2 border-dashed border-accent/70 bg-accent/5 flex flex-col items-center justify-center">
            <div class="h-16 w-16 rounded-2xl bg-accent/15 flex items-center justify-center">
              <Upload class="w-8 h-8 text-accent" />
            </div>
            <p class="mt-4 text-lg font-semibold">松开以添加 .usm 文件</p>
            <p class="mt-1 text-sm text-fg-3">支持文件和文件夹；会根据文件内容自动识别游戏和密钥</p>
            <div class="mt-5 flex gap-2">
              <GameMark v-for="g in GAME_IDS" :key="g" :game="g" :size="26" />
            </div>
          </div>
        </div>
      </Transition>

      <!-- Toasts -->
      <div class="fixed bottom-5 right-5 z-[100] w-[360px] flex flex-col gap-2">
        <TransitionGroup name="toast">
          <div
            v-for="t in toasts" :key="t.id"
            class="rounded-xl border border-line bg-elevated shadow-pop px-4 py-3 flex gap-3"
          >
            <CheckCircle2 v-if="t.kind === 'ok'" class="w-[18px] h-[18px] mt-px shrink-0 text-ok" />
            <XCircle v-else-if="t.kind === 'error'" class="w-[18px] h-[18px] mt-px shrink-0 text-err" />
            <InfoIcon v-else class="w-[18px] h-[18px] mt-px shrink-0 text-accent" />
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium leading-5">{{ t.title }}</p>
              <p v-if="t.text" class="mt-0.5 text-xs leading-5 text-fg-3 break-all selectable">{{ t.text }}</p>
              <button
                v-if="t.action" class="mt-1.5 text-xs font-medium text-accent hover:underline"
                @click="t.action.run(); dismiss(t.id)"
              >{{ t.action.label }}</button>
            </div>
            <button class="h-6 w-6 -mr-1.5 -mt-0.5 shrink-0 rounded-md flex items-center justify-center text-fg-3 hover:text-fg hover:bg-panel-2" @click="dismiss(t.id)">
              <X class="w-3.5 h-3.5" />
            </button>
          </div>
        </TransitionGroup>
      </div>
    </div>
  </TooltipProvider>
</template>
