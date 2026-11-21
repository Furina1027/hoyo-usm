<script setup lang="ts">
import { SwitchRoot, SwitchThumb } from 'reka-ui'

defineProps<{ disabled?: boolean }>()
const model = defineModel<boolean>({ required: true })
</script>

<template>
  <SwitchRoot
    v-model="model" :disabled="disabled"
    class="relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full border border-line transition-colors data-[state=checked]:bg-accent data-[state=checked]:border-accent data-[state=unchecked]:bg-panel-2 data-[disabled]:opacity-45"
  >
    <SwitchThumb
      class="block h-4 w-4 rounded-full bg-white shadow-sm transition-transform translate-x-[2px] data-[state=checked]:translate-x-[18px]"
    />
  </SwitchRoot>
</template>
