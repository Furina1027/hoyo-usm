<script setup lang="ts">
/** 文件详情抽屉：只读解析 USM，展示视频/音轨/密钥/将走的导出管线。 */
import { ref, watch } from 'vue'
import {
  X, AlertTriangle, Film, AudioLines, KeyRound, Boxes, FolderOpen, Download, Copy, Loader2,
} from 'lucide-vue-next'
import {
  api, humanSize, methodLabel, methodTone, fileName, LANG_LABEL, type ProbeReport, type Target,
} from '../api'
import { toast } from '../toast'
import UiButton from './ui/UiButton.vue'
import UiBadge from './ui/UiBadge.vue'

const props = defineProps<{ target: Target, game?: string }>()
const emit = defineEmits<{ close: [], export: [] }>()

const report = ref<ProbeReport | null>(null)
const loading = ref(false)
const error = ref('')

let seq = 0
watch(() => props.target.path, async (path) => {
  const my = ++seq
  loading.value = true
  error.value = ''
  try {
    const r = await api.probe(path, props.game)
    if (my !== seq) return
    if (r.error) { error.value = r.error; report.value = null } else report.value = r
  } catch (e: any) {
    if (my === seq) { error.value = e.message ?? '解析失败'; report.value = null }
  } finally {
    if (my === seq) loading.value = false
  }
}, { immediate: true })

const viaLabel: Record<string, string> = { path: '按完整路径匹配', name: '按文件名匹配', versions: '按版本归档匹配' }

function copy(text: string) {
  navigator.clipboard.writeText(text).then(() => toast('已复制', 'ok')).catch(() => {})
}
</script>

<template>
  <aside class="w-[420px] shrink-0 border-l border-line bg-panel flex flex-col">
    <!-- 头部 -->
    <div class="px-5 pt-5 pb-4 border-b border-line">
      <div class="flex items-start gap-3">
        <div class="h-10 w-10 shrink-0 rounded-xl bg-accent/12 flex items-center justify-center">
          <Film class="w-5 h-5 text-accent" />
        </div>
        <div class="flex-1 min-w-0">
          <p class="font-semibold truncate selectable" :title="target.rel_video">{{ fileName(target.rel_video) }}</p>
          <p class="mt-0.5 text-xs text-fg-3 truncate">{{ target.rel_video }}</p>
        </div>
        <UiButton variant="ghost" size="icon-sm" :icon="X" class="-mr-1.5" title="关闭 (Esc)" @click="emit('close')" />
      </div>
      <div class="mt-4 flex gap-2">
        <UiButton variant="primary" size="sm" :icon="Download" @click="emit('export')">导出此文件</UiButton>
        <UiButton size="sm" :icon="FolderOpen" @click="api.openFolder(target.path, true)">定位文件</UiButton>
        <UiButton size="sm" variant="ghost" :icon="Copy" @click="copy(target.path)">复制路径</UiButton>
      </div>
    </div>

    <!-- 内容 -->
    <div class="flex-1 overflow-auto px-5 py-4 space-y-5 text-sm">
      <!-- 概要 -->
      <dl class="grid grid-cols-3 gap-2">
        <div class="rounded-xl bg-panel-2 px-3 py-2.5">
          <dt class="text-[11px] text-fg-3">大小</dt>
          <dd class="mt-0.5 font-medium tabular">{{ humanSize(target.size) }}</dd>
        </div>
        <div class="rounded-xl bg-panel-2 px-3 py-2.5">
          <dt class="text-[11px] text-fg-3">首次加入</dt>
          <dd class="mt-0.5 font-medium tabular">{{ target.version ?? '—' }}</dd>
        </div>
        <div class="rounded-xl bg-panel-2 px-3 py-2.5">
          <dt class="text-[11px] text-fg-3">来源</dt>
          <dd class="mt-0.5 font-medium">{{ target.source === 'hotfix' ? '热更新' : '本体' }}</dd>
        </div>
      </dl>

      <div v-if="loading && !report" class="flex items-center gap-2 text-fg-3 py-6 justify-center">
        <Loader2 class="w-4 h-4 animate-spin" /> 正在解析文件…
      </div>
      <div v-else-if="error" class="rounded-xl border border-err/30 bg-err/[.07] p-3 text-err text-sm">{{ error }}</div>

      <template v-else-if="report">
        <div v-if="report.warnings.length || report.truncated" class="rounded-xl border border-warn/30 bg-warn/[.07] p-3 space-y-1.5">
          <p v-if="report.truncated" class="flex gap-2 text-err"><AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" /> 文件不完整或已损坏，无法导出</p>
          <p v-for="w in report.warnings" :key="w" class="flex gap-2 text-warn text-[13px] leading-5">
            <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5" /> {{ w }}
          </p>
        </div>

        <!-- 导出管线 -->
        <section>
          <h3 class="text-[11px] font-semibold text-fg-3 uppercase tracking-wider mb-2">导出方式</h3>
          <p class="rounded-xl border border-accent/25 bg-accent/[.06] px-3 py-2.5 text-[13px] leading-5 selectable">{{ report.pipeline }}</p>
        </section>

        <section>
          <h3 class="text-[11px] font-semibold text-fg-3 uppercase tracking-wider mb-2 flex items-center gap-1.5"><Film class="w-3.5 h-3.5" />视频</h3>
          <p class="selectable">{{ report.video.desc }}</p>
          <p class="mt-0.5 text-xs text-fg-3 tabular">{{ report.video.blocks }} 个数据块</p>
        </section>

        <section>
          <h3 class="text-[11px] font-semibold text-fg-3 uppercase tracking-wider mb-2 flex items-center gap-1.5"><AudioLines class="w-3.5 h-3.5" />音轨</h3>
          <div v-if="report.audio.length" class="flex flex-wrap gap-1.5">
            <span v-for="a in report.audio" :key="a.chno" class="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-lg bg-panel-2 border border-line text-xs">
              <span class="font-medium">{{ a.lang ? (LANG_LABEL[a.lang] ?? a.lang) : `轨道 ${a.chno}` }}</span>
              <span class="text-fg-3 uppercase">{{ a.codec }}</span>
            </span>
          </div>
          <p v-else class="text-fg-3">无音轨</p>
        </section>

        <section>
          <h3 class="text-[11px] font-semibold text-fg-3 uppercase tracking-wider mb-2 flex items-center gap-1.5"><KeyRound class="w-3.5 h-3.5" />密钥</h3>
          <div class="flex items-center gap-2">
            <UiBadge :tone="methodTone(report.key?.method)" dot size="md">{{ methodLabel(report.key?.method) }}</UiBadge>
            <span v-if="report.key" class="text-xs text-fg-3">{{ viaLabel[report.key.via] ?? report.key.via }}</span>
          </div>
          <p v-if="report.key?.matched" class="mt-1.5 text-xs text-fg-3 font-mono break-all selectable">{{ report.key.matched }}</p>
        </section>

        <details class="group">
          <summary class="text-[11px] font-semibold text-fg-3 uppercase tracking-wider cursor-pointer list-none flex items-center gap-1.5 hover:text-fg-2">
            <Boxes class="w-3.5 h-3.5" />容器结构
            <span class="normal-case font-normal tracking-normal group-open:hidden">（展开）</span>
          </summary>
          <div class="mt-2 rounded-xl bg-panel-2 p-3 font-mono text-xs space-y-1 selectable">
            <p>块总数：{{ report.blocks }}</p>
            <p v-for="(n, m) in report.magic_hist" :key="m">{{ m }}：{{ n }}</p>
            <p class="break-all">nonce：{{ report.nonce ?? '无' }}</p>
          </div>
        </details>
      </template>
    </div>
  </aside>
</template>
