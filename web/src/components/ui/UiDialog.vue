<script setup lang="ts">
import {
  DialogClose, DialogContent, DialogDescription, DialogOverlay, DialogPortal, DialogRoot, DialogTitle,
} from 'reka-ui'
import { X } from 'lucide-vue-next'

withDefaults(defineProps<{ title: string, description?: string, width?: string }>(), { width: '560px' })
const open = defineModel<boolean>('open', { required: true })
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogPortal>
      <DialogOverlay class="anim-overlay fixed inset-0 z-[70] bg-black/50 backdrop-blur-[2px]" />
      <DialogContent
        class="anim-dialog fixed left-1/2 top-1/2 z-[71] -translate-x-1/2 -translate-y-1/2 max-h-[88vh] flex flex-col rounded-2xl border border-line bg-panel shadow-pop focus:outline-none"
        :style="{ width: `min(${width}, calc(100vw - 48px))` }"
      >
        <div class="flex items-start gap-3 px-6 pt-5 pb-4">
          <div class="flex-1 min-w-0">
            <DialogTitle class="text-base font-semibold">{{ title }}</DialogTitle>
            <DialogDescription v-if="description" class="mt-1 text-sm text-fg-3">{{ description }}</DialogDescription>
          </div>
          <DialogClose class="-mr-2 -mt-1 h-8 w-8 inline-flex items-center justify-center rounded-lg text-fg-3 hover:text-fg hover:bg-panel-2">
            <X class="w-4 h-4" />
          </DialogClose>
        </div>
        <div class="px-6 pb-2 overflow-auto"><slot /></div>
        <div v-if="$slots.footer" class="px-6 py-4 mt-2 flex items-center gap-2 border-t border-line">
          <slot name="footer" />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
