/** 全局状态：设置/主题、环境报告、任务轮询、外部文件暂存。 */

import { computed, reactive, ref } from 'vue'
import { api, type EnvReport, type Settings, type TaskSummary } from './api'

/* ---------------- 设置与主题 ---------------- */

export const settings = ref<Settings | null>(null)

export async function loadSettings(): Promise<Settings> {
  settings.value = await api.settingsGet()
  applyTheme(settings.value.theme)
  return settings.value
}

export async function patchSettings(patch: Partial<Settings>) {
  await api.settingsPut(patch)
  if (settings.value) Object.assign(settings.value, patch)
  if (patch.theme) applyTheme(patch.theme)
}

const media = window.matchMedia('(prefers-color-scheme: dark)')
let currentTheme: string = 'dark'
media.addEventListener('change', () => { if (currentTheme === 'system') applyTheme('system') })

export function applyTheme(theme: string) {
  currentTheme = theme || 'dark'
  const dark = currentTheme === 'system' ? media.matches : currentTheme !== 'light'
  document.documentElement.classList.toggle('dark', dark)
}

/* ---------------- 环境报告（总览/侧栏共用） ---------------- */

export const env = ref<EnvReport | null>(null)
export const envLoading = ref(false)
let envPromise: Promise<void> | null = null

export function loadEnv(refresh = false): Promise<void> {
  if (envPromise && !refresh) return envPromise
  envLoading.value = true
  envPromise = api.env(refresh)
    .then((r) => { env.value = r })
    .finally(() => { envLoading.value = false; envPromise = null })
  return envPromise
}

/* ---------------- 任务轮询 ---------------- */

export const tasks = ref<TaskSummary[]>([])
export const activeTask = computed(() => tasks.value.find(t => t.status === 'running'))
export const queuedTasks = computed(() => tasks.value.filter(t => t.status === 'queued'))
export const busyCount = computed(() => tasks.value.filter(t => t.status === 'running' || t.status === 'queued').length)

const finishListeners = new Set<(t: TaskSummary) => void>()
export function onTaskFinished(fn: (t: TaskSummary) => void) {
  finishListeners.add(fn)
  return () => finishListeners.delete(fn)
}

let pollTimer: number | undefined
let pollBusy = false

export async function refreshTasks() {
  if (pollBusy) return
  pollBusy = true
  try {
    const prev = new Map(tasks.value.map(t => [t.id, t.status]))
    const r = await api.tasks()
    tasks.value = r.tasks
    for (const t of r.tasks) {
      const was = prev.get(t.id)
      if ((was === 'running' || was === 'queued') && !['running', 'queued'].includes(t.status))
        finishListeners.forEach(fn => fn(t))
    }
  } catch { /* 服务短暂不可用：下次重试 */ } finally {
    pollBusy = false
  }
  schedulePoll()
}

function schedulePoll() {
  window.clearTimeout(pollTimer)
  // 有任务时 700ms，空闲时 4s
  pollTimer = window.setTimeout(refreshTasks, busyCount.value ? 700 : 4000)
}

/* ---------------- 外部文件暂存（拖拽 / 选择） ---------------- */

export const staged = reactive<{ paths: string[] }>({ paths: [] })

export function stagePaths(paths: string[]) {
  const set = new Set(staged.paths)
  for (const p of paths) set.add(p)
  staged.paths = [...set]
}
