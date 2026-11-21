<script setup lang="ts">
import { Check, Minus } from 'lucide-vue-next'

defineProps<{ checked: boolean, indeterminate?: boolean, disabled?: boolean }>()
const emit = defineEmits<{ toggle: [e: MouseEvent] }>()
</script>

<template>
  <button
    type="button" role="checkbox" :aria-checked="indeterminate ? 'mixed' : checked" :disabled="disabled"
    class="h-[18px] w-[18px] shrink-0 inline-flex items-center justify-center rounded-[5px] border transition-colors disabled:opacity-40"
    :class="checked || indeterminate
      ? 'bg-accent border-accent text-white'
      : 'border-line-strong bg-panel hover:border-fg-3'"
    @click.stop="emit('toggle', $event)"
  >
    <Minus v-if="indeterminate" class="w-3 h-3" :stroke-width="3" />
    <Check v-else-if="checked" class="w-3 h-3" :stroke-width="3" />
  </button>
</template>
