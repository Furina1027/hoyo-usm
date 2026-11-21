<script setup lang="ts">
defineProps<{ icon?: any, title: string, text?: string }>()
</script>

<template>
  <div class="flex flex-col items-center justify-center text-center py-14 px-6">
    <div v-if="icon" class="h-14 w-14 rounded-2xl bg-panel-2 border border-line flex items-center justify-center">
      <component :is="icon" class="w-6 h-6 text-fg-3" />
    </div>
    <p class="mt-4 text-sm font-medium text-fg">{{ title }}</p>
    <p v-if="text" class="mt-1 text-xs leading-5 text-fg-3 max-w-sm">{{ text }}</p>
    <div v-if="$slots.default" class="mt-5 flex gap-2"><slot /></div>
  </div>
</template>
