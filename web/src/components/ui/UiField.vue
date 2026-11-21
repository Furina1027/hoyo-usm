<script setup lang="ts">
/** 表单行：左侧标签+说明，右侧控件（设置页 / 对话框通用）。 */
defineProps<{ label: string, hint?: string, stacked?: boolean }>()
</script>

<template>
  <div class="py-3.5" :class="stacked ? 'space-y-2' : 'flex items-center gap-6'">
    <div class="min-w-0" :class="!stacked && 'flex-1'">
      <div class="text-sm font-medium text-fg">{{ label }}</div>
      <div v-if="hint" class="mt-0.5 text-xs leading-5 text-fg-3">{{ hint }}</div>
    </div>
    <div :class="stacked ? '' : 'shrink-0'"><slot /></div>
  </div>
</template>
