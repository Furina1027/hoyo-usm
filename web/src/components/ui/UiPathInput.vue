<script setup lang="ts">
/** 路径输入：浏览按钮（窗口模式原生对话框）+ 失焦即时校验 + 打开所在目录。 */
import { ref, watch } from 'vue'
import { CheckCircle2, AlertCircle, FolderOpen, ExternalLink } from 'lucide-vue-next'
import { api, native } from '../../api'
import UiButton from './UiButton.vue'

const props = withDefaults(defineProps<{
  kind?: 'dir' | 'file' | string     // dir / file / game:<gid>
  placeholder?: string
  filePattern?: string
  validate?: boolean
}>(), { kind: 'dir', validate: true })
const model = defineModel<string>({ required: true })

const status = ref<{ ok: boolean, msg: string } | null>(null)
let seq = 0

async function check() {
  if (!props.validate) return
  const v = model.value.trim()
  if (!v) { status.value = null; return }
  const my = ++seq
  try {
    const r = await api.checkPath(v, props.kind)
    if (my === seq) status.value = r
  } catch { status.value = null }
}

watch(model, (v, old) => { if (!old && v) check() })
check()

async function browse() {
  const initial = model.value.trim()
  const p = props.kind === 'file'
    ? await native.pickFile(initial, props.filePattern)
    : await native.pickDirectory(initial)
  if (p) { model.value = p; check() }
}

defineExpose({ check })
</script>

<template>
  <div>
    <div class="flex gap-2">
      <div class="relative flex-1 min-w-0">
        <input
          v-model="model" :placeholder="placeholder" spellcheck="false"
          class="input font-mono text-[13px] pr-9"
          :class="status && !status.ok && 'border-err/60'"
          @blur="check" @keyup.enter="check"
        >
        <span v-if="status" class="absolute right-2.5 top-1/2 -translate-y-1/2">
          <CheckCircle2 v-if="status.ok" class="w-4 h-4 text-ok" />
          <AlertCircle v-else class="w-4 h-4 text-err" />
        </span>
      </div>
      <UiButton v-if="native.available()" :icon="FolderOpen" @click="browse">浏览</UiButton>
      <UiButton
        v-if="model && status?.ok" size="icon" variant="ghost" :icon="ExternalLink" title="在资源管理器中打开"
        @click="api.openFolder(model, kind === 'file')"
      />
    </div>
    <p v-if="status?.msg" class="mt-1.5 text-xs" :class="status.ok ? 'text-fg-3' : 'text-err'">{{ status.msg }}</p>
  </div>
</template>
