<script setup lang="ts" generic="T extends string">
/** 下拉选择（reka-ui Select）。option.value 不能为空串：用 '__all' 之类的哨兵值。 */
import {
  SelectContent, SelectItem, SelectItemIndicator, SelectItemText, SelectPortal,
  SelectRoot, SelectTrigger, SelectValue, SelectViewport,
} from 'reka-ui'
import { Check, ChevronDown } from 'lucide-vue-next'

export interface Option<V> { value: V, label: string, hint?: string, disabled?: boolean }

defineProps<{
  options: Option<T>[]
  placeholder?: string
  disabled?: boolean
  size?: 'sm' | 'md'
  icon?: any
}>()
const model = defineModel<T>({ required: true })
</script>

<template>
  <SelectRoot v-model="model" :disabled="disabled">
    <SelectTrigger
      class="group inline-flex items-center gap-2 justify-between rounded-[10px] border border-line bg-panel-2 text-fg hover:border-line-strong focus:outline-none focus-visible:border-accent data-[disabled]:opacity-45 transition-colors"
      :class="size === 'sm' ? 'h-8 px-2.5 text-xs' : 'h-9 px-3 text-sm'"
    >
      <component :is="icon" v-if="icon" class="w-4 h-4 text-fg-3 shrink-0" />
      <span class="truncate text-left flex-1"><SelectValue :placeholder="placeholder" /></span>
      <ChevronDown class="w-4 h-4 text-fg-3 shrink-0 transition-transform group-data-[state=open]:rotate-180" />
    </SelectTrigger>
    <SelectPortal>
      <SelectContent
        position="popper" :side-offset="6"
        class="anim-pop z-[80] min-w-[var(--reka-select-trigger-width)] max-h-[min(380px,var(--reka-select-content-available-height))] overflow-hidden rounded-xl border border-line bg-elevated shadow-pop"
      >
        <SelectViewport class="p-1">
          <SelectItem
            v-for="o in options" :key="o.value" :value="o.value" :disabled="o.disabled"
            class="relative flex items-center gap-2 h-8 pl-7 pr-3 rounded-lg text-sm text-fg outline-none cursor-pointer data-[highlighted]:bg-accent/12 data-[highlighted]:text-fg data-[disabled]:opacity-40"
          >
            <SelectItemIndicator class="absolute left-2 inline-flex">
              <Check class="w-3.5 h-3.5 text-accent" />
            </SelectItemIndicator>
            <SelectItemText>{{ o.label }}</SelectItemText>
            <span v-if="o.hint" class="ml-auto pl-4 text-xs text-fg-3">{{ o.hint }}</span>
          </SelectItem>
        </SelectViewport>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
