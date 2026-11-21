<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  RefreshCw, FolderOpen, ArrowRight, Sparkles, AlertTriangle, CheckCircle2, KeyRound,
  Cpu, Settings2, FileInput, Clapperboard, HardDrive,
} from 'lucide-vue-next'
import { api, GAME_IDS, GAME_META, humanSize, relTime, type GameId } from '../api'
import { env, envLoading, loadEnv, tasks } from '../store'
import { toastError } from '../toast'
import GameMark from '../components/GameMark.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiBadge from '../components/ui/UiBadge.vue'
import UiTooltip from '../components/ui/UiTooltip.vue'

const router = useRouter()

async function refresh() {
  try { await loadEnv(true) } catch (e) { toastError(e, '刷新失败') }
}

const depsOk = computed(() => Object.values(env.value?.deps ?? {}).every(Boolean))
const missingDeps = computed(() => Object.entries(env.value?.deps ?? {}).filter(([, v]) => !v).map(([k]) => k))

const totals = computed(() => {
  let files = 0, bytes = 0, covered = 0
  for (const g of Object.values(env.value?.games ?? {})) {
    files += g.usm_count ?? 0
    bytes += g.usm_bytes ?? 0
    covered += g.covered ?? 0
  }
  return { files, bytes, covered }
})

const issues = computed(() => {
  const out: { text: string, action?: { label: string, run: () => void } }[] = []
  if (!env.value) return out
  if (!env.value.ffmpeg)
    out.push({ text: '没有找到 ffmpeg，无法导出', action: { label: '去设置', run: () => router.push('/settings') } })
  if (!depsOk.value)
    out.push({ text: `缺少 Python 依赖：${missingDeps.value.join('、')}` })
  for (const gid of GAME_IDS) {
    const g = env.value.games[gid]
    if (g?.error) out.push({ text: `${GAME_META[gid].title}密钥库加载失败：${g.error}` })
  }
  return out
})

const recent = computed(() => tasks.value.filter(t => !['running', 'queued'].includes(t.status)).slice(0, 4))

function pct(g: { covered?: number, usm_count?: number }) {
  if (!g.usm_count) return 0
  return Math.round((g.covered ?? 0) / g.usm_count * 1000) / 10
}

function openFiles(gid: GameId, latest = false) {
  const g = env.value?.games[gid]
  router.push({ name: 'files', query: { game: gid, ...(latest && g?.latest_version ? { version: g.latest_version } : {}) } })
}

onMounted(() => { if (!env.value) loadEnv().catch(() => {}) })
</script>

<template>
  <div class="h-full overflow-auto">
    <div class="max-w-[1180px] mx-auto px-8 py-7 space-y-6">
      <!-- 标题 -->
      <header class="flex items-end gap-4">
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">总览</h1>
          <p class="mt-1 text-sm text-fg-3">
            <template v-if="env">本机共 <span class="text-fg-2 tabular">{{ totals.files }}</span> 个过场动画，合计 {{ humanSize(totals.bytes) }}</template>
            <template v-else>正在读取本机环境…</template>
          </p>
        </div>
        <div class="ml-auto flex gap-2">
          <UiButton :icon="FolderOpen" :disabled="!env" @click="env && api.openFolder(env.out_dir)">输出文件夹</UiButton>
          <UiButton :icon="RefreshCw" :loading="envLoading" @click="refresh">重新扫描</UiButton>
        </div>
      </header>

      <!-- 问题提示 -->
      <div v-if="issues.length" class="rounded-xl border border-warn/30 bg-warn/[.07] px-4 py-3 space-y-1.5">
        <div v-for="(i, k) in issues" :key="k" class="flex items-center gap-2.5 text-sm">
          <AlertTriangle class="w-4 h-4 text-warn shrink-0" />
          <span class="flex-1">{{ i.text }}</span>
          <button v-if="i.action" class="text-xs font-medium text-accent hover:underline" @click="i.action.run">{{ i.action.label }}</button>
        </div>
      </div>

      <!-- 游戏卡片 -->
      <section class="grid grid-cols-3 gap-4">
        <template v-if="env">
          <article
            v-for="gid in GAME_IDS" :key="gid"
            class="card relative overflow-hidden flex flex-col"
          >
            <!-- 顶部色带 -->
            <div class="absolute inset-x-0 top-0 h-24 pointer-events-none"
              :style="{ background: `radial-gradient(120% 100% at 0% 0%, color-mix(in oklab, ${GAME_META[gid].color} 18%, transparent), transparent 70%)` }" />
            <div class="relative p-5 flex-1 flex flex-col">
              <div class="flex items-center gap-3">
                <GameMark :game="gid" :size="38" />
                <div class="min-w-0">
                  <h2 class="font-semibold">{{ GAME_META[gid].title }}</h2>
                  <p class="text-xs text-fg-3">{{ GAME_META[gid].en }}</p>
                </div>
                <UiBadge v-if="env.games[gid].root_found" tone="ok" dot class="ml-auto">已找到</UiBadge>
                <UiBadge v-else tone="neutral" dot class="ml-auto">未找到</UiBadge>
              </div>

              <template v-if="env.games[gid].root_found">
                <div class="mt-6 flex items-baseline gap-2">
                  <span class="text-[34px] leading-none font-semibold tabular tracking-tight">{{ env.games[gid].usm_count ?? 0 }}</span>
                  <span class="text-sm text-fg-3">个文件 · {{ humanSize(env.games[gid].usm_bytes) }}</span>
                </div>

                <!-- 密钥覆盖条 -->
                <div class="mt-4">
                  <div class="flex items-center justify-between text-xs mb-1.5">
                    <span class="text-fg-3">可解密</span>
                    <span class="tabular font-medium" :class="pct(env.games[gid]) >= 100 ? 'text-ok' : 'text-warn'">
                      {{ pct(env.games[gid]) }}%
                    </span>
                  </div>
                  <div class="h-1.5 rounded-full bg-fg/[.07] overflow-hidden flex">
                    <template v-if="env.games[gid].local && env.games[gid].usm_count">
                      <UiTooltip :text="`旧版加密 ${env.games[gid].local!.mask} 个`">
                        <div class="h-full bg-warn" :style="{ width: `${env.games[gid].local!.mask / env.games[gid].usm_count! * 100}%` }" />
                      </UiTooltip>
                      <UiTooltip :text="`新版加密 ${env.games[gid].local!.aes} 个`">
                        <div class="h-full bg-accent" :style="{ width: `${env.games[gid].local!.aes / env.games[gid].usm_count! * 100}%` }" />
                      </UiTooltip>
                      <UiTooltip :text="`未加密 ${env.games[gid].local!.plain} 个`">
                        <div class="h-full bg-fg-3" :style="{ width: `${env.games[gid].local!.plain / env.games[gid].usm_count! * 100}%` }" />
                      </UiTooltip>
                    </template>
                  </div>
                  <div class="mt-2 flex gap-3 text-[11px] text-fg-3">
                    <span class="flex items-center gap-1"><i class="w-1.5 h-1.5 rounded-full bg-warn" />旧版 {{ env.games[gid].local?.mask ?? 0 }}</span>
                    <span class="flex items-center gap-1"><i class="w-1.5 h-1.5 rounded-full bg-accent" />新版 {{ env.games[gid].local?.aes ?? 0 }}</span>
                    <span class="flex items-center gap-1"><i class="w-1.5 h-1.5 rounded-full bg-fg-3" />明文 {{ env.games[gid].local?.plain ?? 0 }}</span>
                    <span v-if="env.games[gid].local?.missing" class="flex items-center gap-1 text-err"><i class="w-1.5 h-1.5 rounded-full bg-err" />缺 {{ env.games[gid].local?.missing }}</span>
                  </div>
                </div>

                <!-- 最新版本 -->
                <button
                  v-if="env.games[gid].latest_version"
                  class="mt-5 w-full flex items-center gap-2.5 rounded-xl px-3 py-2.5 bg-panel-2 border border-line hover:border-line-strong text-left transition-colors group"
                  @click="openFiles(gid, true)"
                >
                  <Sparkles class="w-4 h-4 shrink-0" :style="{ color: GAME_META[gid].color }" />
                  <span class="flex-1 text-sm">
                    <span class="font-medium">{{ env.games[gid].latest_version }}</span>
                    <span class="text-fg-3"> 新增 {{ env.games[gid].latest_new ?? 0 }} 个</span>
                  </span>
                  <ArrowRight class="w-4 h-4 text-fg-3 group-hover:text-fg group-hover:translate-x-0.5 transition-all" />
                </button>

                <div class="mt-auto pt-5 flex items-center gap-2">
                  <UiButton variant="subtle" size="sm" :icon="Clapperboard" @click="openFiles(gid)">浏览全部</UiButton>
                  <UiTooltip :text="env.games[gid].root ?? ''">
                    <UiButton variant="ghost" size="icon-sm" :icon="FolderOpen" class="ml-auto" @click="api.openFolder(env.games[gid].root!)" />
                  </UiTooltip>
                </div>
              </template>

              <template v-else>
                <p class="mt-6 text-sm text-fg-3 leading-6">
                  没有在本机找到{{ GAME_META[gid].title }}。如果已安装，请在设置中手动指定游戏目录；
                  也可以把 .usm 文件拖进窗口单独导出。
                </p>
                <div class="mt-auto pt-5">
                  <UiButton size="sm" :icon="Settings2" @click="router.push('/settings')">指定游戏目录</UiButton>
                </div>
              </template>
            </div>
          </article>
        </template>
        <template v-else>
          <div v-for="i in 3" :key="i" class="card h-[340px] p-5 animate-pulse">
            <div class="flex gap-3"><div class="w-10 h-10 rounded-xl bg-panel-2" /><div class="flex-1 space-y-2 pt-1"><div class="h-3 w-20 rounded bg-panel-2" /><div class="h-2.5 w-28 rounded bg-panel-2" /></div></div>
            <div class="mt-8 h-8 w-24 rounded bg-panel-2" />
            <div class="mt-5 h-1.5 rounded bg-panel-2" />
            <div class="mt-6 h-11 rounded-xl bg-panel-2" />
          </div>
        </template>
      </section>

      <!-- 下半区：环境 + 最近任务 -->
      <section class="grid grid-cols-[1fr_1.3fr] gap-4">
        <div class="card p-5">
          <h3 class="text-sm font-semibold">运行环境</h3>
          <ul class="mt-3 divide-y divide-line text-sm">
            <li class="py-2.5 flex items-center gap-3">
              <Cpu class="w-4 h-4 text-fg-3" />
              <span class="w-20 text-fg-2">ffmpeg</span>
              <span class="flex-1 min-w-0 truncate font-mono text-xs text-fg-3" :title="env?.ffmpeg ?? ''">{{ env?.ffmpeg ?? '未找到' }}</span>
              <CheckCircle2 v-if="env?.ffmpeg" class="w-4 h-4 text-ok" />
              <AlertTriangle v-else-if="env" class="w-4 h-4 text-err" />
            </li>
            <li class="py-2.5 flex items-center gap-3">
              <KeyRound class="w-4 h-4 text-fg-3" />
              <span class="w-20 text-fg-2">密钥库</span>
              <span class="flex-1 min-w-0 truncate text-xs text-fg-3">
                {{ env?.keys_source === 'user' ? '已更新的副本' : env?.keys_source === 'custom' ? '自定义目录' : '内置快照' }}
              </span>
              <CheckCircle2 v-if="env && !issues.some(i => i.text.includes('密钥'))" class="w-4 h-4 text-ok" />
            </li>
            <li class="py-2.5 flex items-center gap-3">
              <HardDrive class="w-4 h-4 text-fg-3" />
              <span class="w-20 text-fg-2">输出</span>
              <span class="flex-1 min-w-0 truncate font-mono text-xs text-fg-3" :title="env?.out_dir">{{ env?.out_dir ?? '—' }}</span>
            </li>
          </ul>
        </div>

        <div class="card p-5 flex flex-col">
          <div class="flex items-center">
            <h3 class="text-sm font-semibold">最近导出</h3>
            <button class="ml-auto text-xs text-fg-3 hover:text-fg flex items-center gap-1" @click="router.push('/tasks')">
              全部 <ArrowRight class="w-3.5 h-3.5" />
            </button>
          </div>
          <div v-if="!recent.length" class="flex-1 flex flex-col items-center justify-center py-6 text-center">
            <p class="text-sm text-fg-3">还没有导出过</p>
            <div class="mt-3 flex gap-2">
              <UiButton size="sm" variant="subtle" :icon="Clapperboard" @click="router.push('/files')">选择游戏文件</UiButton>
              <UiButton size="sm" variant="ghost" :icon="FileInput" @click="router.push('/external')">导入外部文件</UiButton>
            </div>
          </div>
          <ul v-else class="mt-2 divide-y divide-line">
            <li v-for="t in recent" :key="t.id" class="py-2.5 flex items-center gap-3 text-sm">
              <GameMark :game="t.game" :size="22" />
              <span class="tabular">{{ t.total }} 个文件</span>
              <UiBadge v-if="t.status === 'done' && !t.fail" tone="ok">完成</UiBadge>
              <UiBadge v-else-if="t.status === 'done'" tone="warn">{{ t.fail }} 个失败</UiBadge>
              <UiBadge v-else-if="t.status === 'cancelled'" tone="neutral">已取消</UiBadge>
              <UiBadge v-else tone="err">出错</UiBadge>
              <span class="ml-auto text-xs text-fg-3">{{ relTime(t.created) }}</span>
              <UiButton size="icon-sm" variant="ghost" :icon="FolderOpen" title="打开文件夹" @click="api.openFolder(t.out_dir)" />
            </li>
          </ul>
        </div>
      </section>
    </div>
  </div>
</template>
