<script setup lang="ts" generic="T extends string">
/** 分段选择器（少量互斥选项，比下拉更直观）。 */
defineProps<{
  options: { value: T, label: string, icon?: any, disabled?: boolean, hint?: string }[]
  size?: 'sm' | 'md'
  block?: boolean
}>()
const model = defineModel<T>({ required: true })
</script>

<template>
  <div
    class="inline-flex p-[3px] rounded-[11px] bg-panel-2 border border-line gap-[2px]"
    :class="block && 'flex w-full'"
    role="radiogroup"
  >
    <button
      v-for="o in options" :key="o.value"
      role="radio" :aria-checked="model === o.value" :disabled="o.disabled" :title="o.hint"
      class="inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all disabled:opacity-40"
      :class="[
        size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3.5 text-sm',
        block && 'flex-1',
        model === o.value
          ? 'bg-elevated text-fg shadow-[0_1px_3px_rgb(0_0_0/.18)] ring-1 ring-line'
          : 'text-fg-3 hover:text-fg-2',
      ]"
      @click="model = o.value"
    >
      <component :is="o.icon" v-if="o.icon" class="w-3.5 h-3.5" />
      {{ o.label }}
    </button>
  </div>
</template>
