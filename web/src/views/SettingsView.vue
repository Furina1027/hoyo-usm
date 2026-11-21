<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { onBeforeRouteLeave } from 'vue-router'
import {
  Save, RefreshCw, Download, RotateCcw, Gamepad2, HardDrive, KeyRound, Palette, Undo2, Sun, Moon, Monitor,
} from 'lucide-vue-next'
import { api, GAME_IDS, GAME_META, type Settings } from '../api'
import { loadEnv, loadSettings, patchSettings, settings } from '../store'
import { toast, toastError } from '../toast'
import GameMark from '../components/GameMark.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiField from '../components/ui/UiField.vue'
import UiPathInput from '../components/ui/UiPathInput.vue'
import UiSegmented from '../components/ui/UiSegmented.vue'
import UiSelect from '../components/ui/UiSelect.vue'

const router = useRouter()

type Form = Pick<Settings, 'keys_dir' | 'ffmpeg_path' | 'out_dir' | 'key_update_url' | 'theme'> & {
  game_roots: Record<string, string>, jobs: string
}
const form = ref<Form | null>(null)
const original = ref('')
const saving = ref(false)
const detecting = ref(false)
const updating = ref(false)
const backups = ref<string[]>([])
const rollbackTo = ref('bundled')

function fromSettings(s: Settings): Form {
  return {
    keys_dir: s.keys_dir ?? '',
    game_roots: { gi: s.game_roots?.gi ?? '', hsr: s.game_roots?.hsr ?? '', zzz: s.game_roots?.zzz ?? '' },
    ffmpeg_path: s.ffmpeg_path ?? '',
    out_dir: s.out_dir ?? '',
    jobs: String(s.jobs ?? 1),
    theme: s.theme ?? 'dark',
    key_update_url: s.key_update_url ?? '',
  }
}

async function load() {
  const s = await loadSettings()
  form.value = fromSettings(s)
  original.value = JSON.stringify(form.value)
  try { backups.value = (await api.keysBackups()).backups } catch { backups.value = [] }
}

const dirty = computed(() => !!form.value && JSON.stringify(form.value) !== original.value)

async function save() {
  if (!form.value) return
  saving.value = true
  try {
    const f = form.value
    await patchSettings({
      keys_dir: f.keys_dir.trim(), game_roots: { ...f.game_roots }, ffmpeg_path: f.ffmpeg_path.trim(),
      out_dir: f.out_dir.trim(), jobs: Number(f.jobs), theme: f.theme, key_update_url: f.key_update_url.trim(),
    })
    original.value = JSON.stringify(f)
    await loadSettings()
    loadEnv(true).catch(() => {})
    toast('设置已保存', 'ok')
  } catch (e) { toastError(e, '保存失败') } finally { saving.value = false }
}

function revert() { form.value = JSON.parse(original.value) }

/** 主题即时生效并保存（不需要点保存）。 */
function setTheme(t: Settings['theme']) {
  if (!form.value) return
  form.value.theme = t
  const o = JSON.parse(original.value); o.theme = t; original.value = JSON.stringify(o)
  patchSettings({ theme: t }).catch(() => {})
}

async function detect() {
  if (!form.value) return
  detecting.value = true
  try {
    let result: Record<string, string | null> = {}
    for (let i = 0; i < 60; i++) {
      const r = await api.detect()
      if (r.done) { result = r.result ?? {}; break }
      await new Promise(s => setTimeout(s, 800))
    }
    let n = 0
    for (const g of GAME_IDS) {
      const p = result[g]
      if (p && form.value.game_roots[g] !== p) { form.value.game_roots[g] = p; n++ }
    }
    toast(n ? `检测到 ${n} 个游戏目录，记得保存` : '没有发现新的游戏目录', n ? 'ok' : 'info')
  } finally { detecting.value = false }
}

async function updateKeys() {
  updating.value = true
  try {
    if (dirty.value) await save()
    const r = await api.keysUpdate(form.value?.key_update_url.trim() || undefined)
    toast({ kind: 'ok', title: '密钥库已更新', text: `旧版本已备份到 ${r.backup}` })
    backups.value = (await api.keysBackups()).backups
    loadEnv(true).catch(() => {})
  } catch (e) { toastError(e, '更新失败') } finally { updating.value = false }
}

async function rollback() {
  try {
    await api.keysRollback(rollbackTo.value)
    toast(rollbackTo.value === 'bundled' ? '已恢复为内置密钥快照' : `已回滚到 ${rollbackTo.value}`, 'ok')
    loadEnv(true).catch(() => {})
  } catch (e) { toastError(e, '回滚失败') }
}

const rollbackOptions = computed(() => [
  { value: 'bundled', label: '内置快照' },
  ...backups.value.map(b => ({ value: b, label: b.replace(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/, '$1-$2-$3 $4:$5') })),
])

async function rerunWizard() {
  await patchSettings({ wizard_done: false })
  router.push('/wizard')
}

const sections = [
  { id: 'games', label: '游戏目录', icon: Gamepad2 },
  { id: 'export', label: '导出与路径', icon: HardDrive },
  { id: 'keys', label: '密钥库', icon: KeyRound },
  { id: 'look', label: '外观', icon: Palette },
]
const scrollEl = ref<HTMLElement | null>(null)
const activeSection = ref('games')
function goto(id: string) {
  document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function onScroll() {
  const top = scrollEl.value?.getBoundingClientRect().top ?? 0
  for (const s of [...sections].reverse()) {
    const el = document.getElementById(`sec-${s.id}`)
    if (el && el.getBoundingClientRect().top - top < 120) { activeSection.value = s.id; return }
  }
  activeSection.value = sections[0].id
}

onBeforeRouteLeave(() => {
  if (dirty.value) return window.confirm('有未保存的修改，确定离开吗？')
})

onMounted(load)
const jobOptions = ['1', '2', '3', '4', '6', '8'].map(v => ({ value: v, label: `${v} 个` }))
</script>

<template>
  <div class="h-full flex flex-col">
    <header class="px-8 pt-7 pb-5 flex items-end gap-4 border-b border-line">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">设置</h1>
        <p class="mt-1 text-xs text-fg-3 font-mono">{{ settings?.app_data_dir }}</p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <Transition name="fade">
          <span v-if="dirty" class="text-xs text-warn mr-1">有未保存的修改</span>
        </Transition>
        <UiButton v-if="dirty" variant="ghost" :icon="Undo2" @click="revert">还原</UiButton>
        <UiButton variant="primary" :icon="Save" :loading="saving" :disabled="!dirty" @click="save">保存</UiButton>
      </div>
    </header>

    <div v-if="form" class="flex-1 min-h-0 flex">
      <nav class="w-48 shrink-0 px-4 py-6 space-y-0.5">
        <button
          v-for="s in sections" :key="s.id"
          class="w-full h-9 px-3 rounded-[10px] flex items-center gap-2.5 text-sm transition-colors"
          :class="activeSection === s.id ? 'bg-panel-2 text-fg font-medium' : 'text-fg-3 hover:text-fg'"
          @click="goto(s.id)"
        >
          <component :is="s.icon" class="w-4 h-4" />{{ s.label }}
        </button>
      </nav>

      <div ref="scrollEl" class="flex-1 overflow-auto pr-8 py-6" @scroll="onScroll">
        <div class="max-w-[760px] space-y-6 pb-[40vh]">
          <!-- 游戏目录 -->
          <section id="sec-games" class="card p-6">
            <div class="flex items-center">
              <div>
                <h2 class="font-semibold">游戏目录</h2>
                <p class="mt-0.5 text-xs text-fg-3">包含游戏主程序（如 YuanShen.exe、StarRail.exe）的文件夹</p>
              </div>
              <UiButton class="ml-auto" size="sm" :icon="RefreshCw" :loading="detecting" @click="detect">自动检测</UiButton>
            </div>
            <div class="mt-5 space-y-4">
              <div v-for="g in GAME_IDS" :key="g" class="flex gap-3">
                <GameMark :game="g" :size="36" class="mt-0.5" />
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium mb-1.5">{{ GAME_META[g].title }}</p>
                  <UiPathInput v-model="form.game_roots[g]" :kind="`game:${g}`" placeholder="未设置：将自动检测" />
                </div>
              </div>
            </div>
          </section>

          <!-- 导出与路径 -->
          <section id="sec-export" class="card p-6">
            <h2 class="font-semibold">导出与路径</h2>
            <div class="mt-2 divide-y divide-line">
              <UiField label="默认输出文件夹" :hint="`留空使用：${settings?.out_dir_effective}`" stacked>
                <UiPathInput v-model="form.out_dir" kind="dir" :validate="false" placeholder="留空使用默认位置" />
              </UiField>
              <UiField label="ffmpeg" :hint="settings?.ffmpeg_effective ? `当前使用：${settings.ffmpeg_effective}` : '没有找到 ffmpeg，导出前必须指定'" stacked>
                <UiPathInput v-model="form.ffmpeg_path" kind="file" file-pattern="ffmpeg (ffmpeg.exe)" placeholder="留空自动查找（随包 / PATH）" />
              </UiField>
              <UiField label="默认并行数" hint="导出对话框里的初始值；SSD 可以开大一些">
                <UiSelect v-model="form.jobs" :options="jobOptions" class="w-28" size="sm" />
              </UiField>
            </div>
          </section>

          <!-- 密钥库 -->
          <section id="sec-keys" class="card p-6">
            <h2 class="font-semibold">密钥库</h2>
            <p class="mt-0.5 text-xs text-fg-3 leading-5">
              内置一份密钥快照，可离线使用。游戏更新后如果新动画显示“缺密钥”，可以从更新源拉取最新数据；更新前会自动备份。
            </p>
            <div class="mt-2 divide-y divide-line">
              <UiField label="更新源" hint="密钥仓库 raw 目录的 URL" stacked>
                <div class="flex gap-2">
                  <input v-model="form.key_update_url" class="input font-mono text-[13px]" spellcheck="false" placeholder="https://raw.githubusercontent.com/…/usm">
                  <UiButton :icon="Download" :loading="updating" :disabled="!form.key_update_url.trim()" @click="updateKeys">立即更新</UiButton>
                </div>
              </UiField>
              <UiField label="回滚" hint="恢复到更新前的某个备份，或回到内置快照">
                <div class="flex gap-2">
                  <UiSelect v-model="rollbackTo" :options="rollbackOptions" class="w-44" size="sm" />
                  <UiButton size="sm" :icon="RotateCcw" @click="rollback">回滚</UiButton>
                </div>
              </UiField>
              <UiField label="自定义密钥目录" :hint="`当前使用：${settings?.keys_dir_effective}`" stacked>
                <UiPathInput v-model="form.keys_dir" kind="dir" placeholder="留空自动选择（一般不需要改）" />
              </UiField>
            </div>
          </section>

          <!-- 外观 -->
          <section id="sec-look" class="card p-6">
            <h2 class="font-semibold">外观</h2>
            <div class="mt-2 divide-y divide-line">
              <UiField label="主题" hint="立即生效">
                <UiSegmented
                  :model-value="form.theme" size="sm"
                  :options="[{ value: 'dark', label: '深色', icon: Moon }, { value: 'light', label: '浅色', icon: Sun }, { value: 'system', label: '跟随系统', icon: Monitor }]"
                  @update:model-value="setTheme($event as Settings['theme'])"
                />
              </UiField>
              <UiField label="初始向导" hint="重新走一遍首次启动的配置流程">
                <UiButton size="sm" variant="ghost" @click="rerunWizard">重新运行</UiButton>
              </UiField>
            </div>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>
