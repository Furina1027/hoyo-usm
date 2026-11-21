<script setup lang="ts">
import { TooltipContent, TooltipPortal, TooltipRoot, TooltipTrigger } from 'reka-ui'

withDefaults(defineProps<{ text?: string, side?: 'top' | 'right' | 'bottom' | 'left', disabled?: boolean }>(), { side: 'top' })
</script>

<template>
  <TooltipRoot :disabled="disabled || !text">
    <TooltipTrigger as-child><slot /></TooltipTrigger>
    <TooltipPortal>
      <TooltipContent
        :side="side" :side-offset="6"
        class="anim-pop z-[90] max-w-xs rounded-lg bg-fg text-bg px-2.5 py-1.5 text-xs leading-5 shadow-pop"
      >
        {{ text }}
      </TooltipContent>
    </TooltipPortal>
  </TooltipRoot>
</template>
