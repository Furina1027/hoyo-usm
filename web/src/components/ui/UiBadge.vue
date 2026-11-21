<script setup lang="ts">
import type { Tone } from '../../api'

withDefaults(defineProps<{ tone?: Tone, dot?: boolean, size?: 'sm' | 'md' }>(), { tone: 'neutral', size: 'sm' })

const tones: Record<Tone, string> = {
  neutral: 'bg-fg/[.06] text-fg-2',
  accent: 'bg-accent/12 text-accent',
  ok: 'bg-ok/12 text-ok',
  warn: 'bg-warn/12 text-warn',
  err: 'bg-err/12 text-err',
}
const dots: Record<Tone, string> = {
  neutral: 'bg-fg-3', accent: 'bg-accent', ok: 'bg-ok', warn: 'bg-warn', err: 'bg-err',
}
</script>

<template>
  <span
    class="inline-flex items-center gap-1.5 rounded-md font-medium whitespace-nowrap"
    :class="[tones[tone], size === 'sm' ? 'h-5 px-1.5 text-[11px]' : 'h-6 px-2 text-xs']"
  >
    <span v-if="dot" class="w-1.5 h-1.5 rounded-full" :class="dots[tone]" />
    <slot />
  </span>
</template>
