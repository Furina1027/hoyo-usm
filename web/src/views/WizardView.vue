<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Clapperboard, ShieldCheck, WifiOff, KeyRound, ArrowRight, ArrowLeft, RefreshCw, Check } from 'lucide-vue-next'
import { api, GAME_IDS, GAME_META } from '../api'
import { loadEnv, patchSettings } from '../store'
import { toastError } from '../toast'
import GameMark from '../components/GameMark.vue'
import UiButton from '../components/ui/UiButton.vue'
import UiPathInput from '../components/ui/UiPathInput.vue'

const router = useRouter()
const step = ref(1)
const scanning = ref(false)
const roots = reactive<Record<string, string>>({ gi: '', hsr: '', zzz: '' })
const saving = ref(false)

async function detect() {
  scanning.value = true
  try {
    for (let i = 0; i < 60; i++) {
      const r = await api.detect()
      if (r.done) {
        for (const g of GAME_IDS) if (r.result?.[g] && !roots[g]) roots[g] = r.result[g]!
        break
      }
      await new Promise(s => setTimeout(s, 800))
    }
  } finally { scanning.value = false }
}

function next() { step.value = 2; detect() }

const found = computed(() => GAME_IDS.filter(g => roots[g]).length)

async function finish() {
  saving.value = true
  try {
    const clean = Object.fromEntries(Object.entries(roots).map(([k, v]) => [k, v.trim()]))
    await patchSettings({ game_roots: clean, wizard_done: true })
    loadEnv(true).catch(() => {})
    router.replace('/')
  } catch (e) { toastError(e, '保存失败') } finally { saving.value = false }
}

async function skip() {
  await patchSettings({ wizard_done: true }).catch(() => {})
  router.replace('/')
}
</script>

<template>
  <div class="h-full overflow-auto flex items-center justify-center p-8 relative">
    <!-- 背景光晕 -->
    <div class="absolute inset-0 pointer-events-none overflow-hidden">
      <div class="absolute -top-40 left-1/4 w-[520px] h-[520px] rounded-full blur-[120px] opacity-25" style="background: var(--color-hsr)" />
      <div class="absolute -bottom-40 right-1/4 w-[480px] h-[480px] rounded-full blur-[120px] opacity-20" style="background: var(--color-gi)" />
    </div>

    <div class="relative w-full max-w-[640px]">
      <!-- 步骤指示 -->
      <div class="flex items-center justify-center gap-2 mb-6">
        <span v-for="i in 2" :key="i" class="h-1.5 rounded-full transition-all" :class="step === i ? 'w-8 bg-accent' : 'w-1.5 bg-line-strong'" />
      </div>

      <Transition name="page" mode="out-in">
        <!-- 步骤 1：欢迎 -->
        <div v-if="step === 1" key="1" class="card shadow-pop p-9">
          <div class="h-14 w-14 rounded-2xl bg-gradient-to-br from-accent-2 to-accent flex items-center justify-center shadow-[0_10px_30px_-10px_var(--c-accent)]">
            <Clapperboard class="w-7 h-7 text-white" />
          </div>
          <h1 class="mt-6 text-[26px] font-semibold tracking-tight">欢迎使用 hoyo-usm</h1>
          <p class="mt-2 text-fg-2 leading-7">
            把本机原神、星穹铁道、绝区零的过场动画解密并导出为普通视频文件，画面原样保留，不重新编码。
          </p>
          <div class="mt-6 flex gap-2">
            <GameMark v-for="g in GAME_IDS" :key="g" :game="g" :size="30" />
          </div>
          <ul class="mt-7 space-y-3.5 text-sm">
            <li class="flex gap-3"><ShieldCheck class="w-5 h-5 text-ok shrink-0" /><span class="text-fg-2">只读取游戏目录里的视频文件，不修改游戏</span></li>
            <li class="flex gap-3"><WifiOff class="w-5 h-5 text-accent shrink-0" /><span class="text-fg-2">完全离线运行；只有你手动更新密钥时才会联网</span></li>
            <li class="flex gap-3"><KeyRound class="w-5 h-5 text-warn shrink-0" /><span class="text-fg-2">密钥来自社区维护的快照，已内置在程序里</span></li>
          </ul>
          <p class="mt-7 text-xs text-fg-3 leading-5">仅供个人学习观看，请勿传播导出内容。本工具与米哈游无关。</p>
          <div class="mt-7 flex items-center gap-2">
            <UiButton variant="primary" size="lg" @click="next">开始设置 <ArrowRight class="w-4 h-4" /></UiButton>
            <UiButton variant="ghost" size="lg" @click="skip">跳过</UiButton>
          </div>
        </div>

        <!-- 步骤 2：游戏目录 -->
        <div v-else key="2" class="card shadow-pop p-9">
          <div class="flex items-start">
            <div>
              <h1 class="text-xl font-semibold tracking-tight">找到你的游戏</h1>
              <p class="mt-1.5 text-sm text-fg-3">
                <template v-if="scanning">正在扫描注册表和各个磁盘…</template>
                <template v-else>已找到 {{ found }} 个。没装的游戏留空即可，之后也可以在设置里修改。</template>
              </p>
            </div>
            <UiButton class="ml-auto" size="sm" variant="ghost" :icon="RefreshCw" :loading="scanning" @click="detect">重新扫描</UiButton>
          </div>

          <div class="mt-6 space-y-4">
            <div v-for="g in GAME_IDS" :key="g" class="rounded-xl border p-4 transition-colors" :class="roots[g] ? 'border-line-strong bg-panel-2/50' : 'border-line'">
              <div class="flex items-center gap-2.5 mb-2.5">
                <GameMark :game="g" :size="26" />
                <span class="text-sm font-medium">{{ GAME_META[g].title }}</span>
                <span v-if="roots[g]" class="ml-auto text-xs text-ok flex items-center gap-1"><Check class="w-3.5 h-3.5" />已找到</span>
                <span v-else-if="scanning" class="ml-auto text-xs text-fg-3">扫描中…</span>
                <span v-else class="ml-auto text-xs text-fg-3">未安装或未找到</span>
              </div>
              <UiPathInput v-model="roots[g]" :kind="`game:${g}`" placeholder="游戏主程序所在的文件夹" />
            </div>
          </div>

          <div class="mt-7 flex items-center gap-2">
            <UiButton variant="ghost" @click="step = 1"><ArrowLeft class="w-4 h-4" />上一步</UiButton>
            <span class="ml-auto text-xs text-fg-3">没装游戏也能用：把 .usm 拖进窗口即可</span>
            <UiButton variant="primary" size="lg" :loading="saving" @click="finish">完成</UiButton>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>
