<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'subtle'
  size?: 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm'
  loading?: boolean
  disabled?: boolean
  icon?: any
  type?: 'button' | 'submit'
}>(), { variant: 'secondary', size: 'md', type: 'button' })

const cls = computed(() => {
  const base = 'relative inline-flex items-center justify-center gap-1.5 font-medium whitespace-nowrap select-none transition-[background,color,border-color,box-shadow,transform] duration-150 active:scale-[.98] disabled:opacity-45 disabled:active:scale-100'
  const size = {
    sm: 'h-7 px-2.5 text-xs rounded-lg',
    md: 'h-9 px-3.5 text-sm rounded-[10px]',
    lg: 'h-11 px-5 text-[0.95rem] rounded-xl',
    icon: 'h-9 w-9 rounded-[10px]',
    'icon-sm': 'h-7 w-7 rounded-lg',
  }[props.size]
  const variant = {
    primary: 'text-accent-fg bg-gradient-to-b from-accent-2 to-accent shadow-[0_1px_0_rgb(255_255_255/.18)_inset,0_6px_16px_-6px_var(--c-accent)] hover:brightness-110',
    secondary: 'bg-panel-2 text-fg border border-line hover:border-line-strong hover:bg-elevated',
    ghost: 'text-fg-2 hover:text-fg hover:bg-panel-2',
    subtle: 'text-accent bg-accent/10 hover:bg-accent/15',
    danger: 'text-err bg-err/10 hover:bg-err/15',
  }[props.variant]
  return [base, size, variant]
})
const iconCls = computed(() => props.size === 'sm' || props.size === 'icon-sm' ? 'w-3.5 h-3.5' : 'w-4 h-4')
</script>

<template>
  <button :type="type" :class="cls" :disabled="disabled || loading">
    <Loader2 v-if="loading" :class="[iconCls, 'animate-spin']" />
    <component :is="icon" v-else-if="icon" :class="iconCls" />
    <slot />
  </button>
</template>
