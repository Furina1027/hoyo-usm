/** 后端 API 客户端（类型化 fetch 封装）。 */

export type GameId = 'gi' | 'hsr' | 'zzz'

export interface GameEnv {
  title: string
  codename: string
  has_audio: boolean
  keys?: { total: number, mask: number, aes: number, plain: number, dropped: number, aes_with_audio: number }
  by_path?: number
  history?: number | null
  latest_version?: string | null
  latest_new?: number | null
  root?: string | null
  root_found: boolean
  detected?: string | null
  usm_count?: number
  usm_bytes?: number
  covered?: number
  local?: { mask: number, aes: number, plain: number, missing: number }
  error?: string
}

export interface EnvReport {
  ffmpeg: string | null
  deps: Record<string, boolean>
  keys_dir: string
  keys_source: 'bundled' | 'user' | 'custom'
  out_dir: string
  games: Record<GameId, GameEnv>
}

export interface Target {
  game_id: string
  rel_video: string
  path: string
  source: string
  entry_method: string | null
  entry_key_hex: string | null
  entry_audio_hex: string | null
  via: string | null
  cls: string | null
  size: number
  version: string | null
}

export interface FilesReport {
  game: string
  title: string
  has_audio: boolean
  langs: Record<number, string> | null
  versions: string[]
  root: string
  targets: Target[]
}

export interface ProbeReport {
  file: string
  size: number
  game: string
  game_title: string
  codename: string
  blocks: number
  magic_hist: Record<string, number>
  truncated: boolean
  unknown_magics: Record<string, number>
  video: { blocks: number, kind: string, desc: string, ivf: Record<string, unknown> | null }
  nonce: string | null
  audio: { chno: number, codec: string, blocks: number, lang: string | null }[]
  key: { method: string, audio: string | null, via: string, matched: string } | null
  pipeline: string
  warnings: string[]
  error?: string
}

export type TaskStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export interface TaskSummary {
  id: string
  game: string
  status: TaskStatus
  total: number
  done: number
  ok: number
  skip: number
  fail: number
  cancelled: number
  error: string
  report_path: string
  out_dir: string
  created: number
  started: number | null
  finished: number | null
  options: { audio: string, audio_format: string, container: string, verify: boolean, jobs: number }
  current: string[]
}

export interface TaskResult {
  rel: string
  status: 'ok' | 'skip' | 'fail' | 'cancelled'
  msg: string
  output: string | null
  seconds: number
  method: string
  notes: string[]
  size: number
}

export interface IdentifyResult {
  path: string
  game?: GameId
  game_title?: string
  rel_video?: string
  source?: string
  method?: string | null
  audio?: string | null
  via?: string | null
  size?: number
  error?: string
}

export interface ExportOptions {
  audio: string
  audio_format: string
  container: string
  verify: boolean
  jobs: number
  out_dir?: string
}

export interface ExportParams extends ExportOptions {
  game?: string
  paths?: string[]
  mode?: string
  version?: string
  filter?: string
  limit?: number
}

export interface Settings {
  keys_dir: string
  game_roots: Record<string, string>
  ffmpeg_path: string
  out_dir: string
  jobs: number
  theme: 'dark' | 'light' | 'system'
  wizard_done: boolean
  key_update_url: string
  audio: string
  audio_format: string
  container: string
  verify: boolean
  keys_dir_effective: string
  keys_dir_bundled: string
  out_dir_effective: string
  ffmpeg_effective: string | null
  app_data_dir: string
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(url, init)
  } catch {
    throw new ApiError(0, '无法连接本地服务：应用可能已退出')
  }
  const text = await resp.text()
  let data: any = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!resp.ok) {
    let msg = text || `HTTP ${resp.status}`
    if (data && typeof data === 'object' && 'detail' in data)
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    throw new ApiError(resp.status, msg)
  }
  return data as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
})

function qs(q: Record<string, string | number | boolean | undefined>): string {
  return new URLSearchParams(
    Object.entries(q).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)])).toString()
}

export const api = {
  env: (refresh = false) => request<EnvReport>(`/api/env${refresh ? '?refresh=true' : ''}`),
  detect: () => request<{ result: Record<string, string | null> | null, done: boolean }>('/api/detect'),
  checkPath: (path: string, kind: string) =>
    request<{ ok: boolean, msg: string, count?: number }>('/api/check-path', json('POST', { path, kind })),
  files: (q: Record<string, string | number | boolean | undefined>) => request<FilesReport>('/api/files?' + qs(q)),
  versions: (game: string) => request<{ versions: string[], latest: string | null }>(`/api/versions?game=${game}`),
  probe: (path: string, game?: string) => request<ProbeReport>('/api/probe?' + qs({ path, game })),
  expand: (paths: string[]) => request<{ files: string[] }>('/api/expand', json('POST', { paths })),
  identify: (paths: string[]) => request<{ results: IdentifyResult[] }>('/api/identify', json('POST', { paths })),
  scanDir: (dir: string) => request<{ dir: string, files: string[] }>('/api/scan-dir', json('POST', { dir })),
  export: (params: ExportParams) =>
    request<{ task_id: string, total: number, out_dir: string }>('/api/export', json('POST', params)),
  tasks: () => request<{ tasks: TaskSummary[] }>('/api/tasks'),
  task: (id: string) => request<TaskSummary & { results: TaskResult[] }>(`/api/tasks/${id}`),
  cancelTask: (id: string) => request<{ ok: boolean }>(`/api/tasks/${id}/cancel`, { method: 'POST' }),
  deleteTask: (id: string) => request<{ ok: boolean }>(`/api/tasks/${id}`, { method: 'DELETE' }),
  clearTasks: () => request<{ ok: boolean, removed: number }>('/api/tasks', { method: 'DELETE' }),
  settingsGet: () => request<Settings>('/api/settings'),
  settingsPut: (patch: Partial<Settings>) => request<{ ok: boolean }>('/api/settings', json('PUT', patch)),
  keysUpdate: (url?: string) =>
    request<{ ok: boolean, target_dir: string, backup: string, counts: Record<string, number | null> }>(
      '/api/keys/update', json('POST', { url })),
  keysBackups: () => request<{ backups: string[] }>('/api/keys/backups'),
  keysRollback: (name: string) => request<{ ok: boolean }>('/api/keys/rollback', json('POST', { dir: name })),
  openFolder: (path: string, select = false) => request<{ ok: boolean }>('/api/open-folder', json('POST', { path, select })),
  openFile: (path: string) => request<{ ok: boolean }>('/api/open-file', json('POST', { path })),
}

/* ---------------- 原生桥（pywebview 窗口模式） ---------------- */

function bridge(): any {
  return (window as any).pywebview?.api ?? null
}

export const native = {
  available: () => !!bridge(),
  pickUsmFiles: async (): Promise<string[]> => (await bridge()?.pick_usm_files()) ?? [],
  pickDirectory: async (initial = ''): Promise<string> => (await bridge()?.pick_directory(initial)) ?? '',
  pickFile: async (initial = '', pattern = '全部文件 (*.*)'): Promise<string> =>
    (await bridge()?.pick_file(initial, pattern)) ?? '',
}

/** pywebview 注入较晚：等待 ready 事件（浏览器模式下 1.5s 超时返回 false）。 */
export function whenNativeReady(): Promise<boolean> {
  if (bridge()) return Promise.resolve(true)
  return new Promise((resolve) => {
    const t = setTimeout(() => resolve(false), 1500)
    window.addEventListener('pywebviewready', () => { clearTimeout(t); resolve(true) }, { once: true })
  })
}

/* ---------------- 展示辅助 ---------------- */

export const GAME_IDS: GameId[] = ['gi', 'hsr', 'zzz']

export const GAME_META: Record<GameId, { title: string, short: string, color: string, en: string }> = {
  gi: { title: '原神', short: '原', color: 'var(--color-gi)', en: 'Genshin Impact' },
  hsr: { title: '星穹铁道', short: '星', color: 'var(--color-hsr)', en: 'Honkai: Star Rail' },
  zzz: { title: '绝区零', short: '绝', color: 'var(--color-zzz)', en: 'Zenless Zone Zero' },
}

export const LANG_LABEL: Record<string, string> = { zho: '中文', eng: '英文', jpn: '日文', kor: '韩文' }

export function humanSize(n: number | undefined | null): string {
  if (!n) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let x = n
  let i = 0
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++ }
  return i === 0 ? `${n} B` : `${x.toFixed(x >= 100 ? 0 : 1)} ${units[i]}`
}

export function humanDuration(sec: number): string {
  if (!isFinite(sec) || sec < 0) return '—'
  sec = Math.round(sec)
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return `${m} 分 ${s.toString().padStart(2, '0')} 秒`
  return `${Math.floor(m / 60)} 时 ${(m % 60).toString().padStart(2, '0')} 分`
}

export function relTime(ts: number): string {
  const d = Date.now() / 1000 - ts
  if (d < 60) return '刚刚'
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`
  const dt = new Date(ts * 1000)
  return `${dt.getMonth() + 1}月${dt.getDate()}日 ${dt.getHours().toString().padStart(2, '0')}:${dt.getMinutes().toString().padStart(2, '0')}`
}

export function methodLabel(m: string | null | undefined): string {
  if (m === 'mask') return '旧版加密'
  if (m === 'aes') return '新版加密'
  if (m === 'plain') return '未加密'
  return '缺密钥'
}

export function methodTone(m: string | null | undefined): Tone {
  if (m === 'mask') return 'warn'
  if (m === 'aes') return 'accent'
  if (m === 'plain') return 'neutral'
  return 'err'
}

export type Tone = 'neutral' | 'accent' | 'ok' | 'warn' | 'err'

export function fileName(p: string): string {
  return p.split(/[\\/]/).pop() ?? p
}

export function dirName(p: string): string {
  const i = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
  return i > 0 ? p.slice(0, i) : ''
}
