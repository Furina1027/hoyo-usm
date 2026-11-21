<script setup lang="ts">
withDefaults(defineProps<{ value: number, max?: number, animated?: boolean, tone?: 'accent' | 'ok' | 'err', height?: number }>(),
  { max: 100, tone: 'accent', height: 6 })
</script>

<template>
  <div class="w-full rounded-full bg-fg/[.07] overflow-hidden" :style="{ height: `${height}px` }">
    <div
      class="h-full rounded-full transition-[width] duration-500 ease-out"
      :class="[
        tone === 'ok' ? 'bg-ok' : tone === 'err' ? 'bg-err' : 'bg-gradient-to-r from-accent to-accent-2',
        animated && 'bar-stripes',
      ]"
      :style="{ width: `${max ? Math.min(100, value / max * 100) : 0}%` }"
    />
  </div>
</template>
