import { reactive } from 'vue'

export interface ToastAction { label: string, run: () => void }
export interface Toast {
  id: number
  kind: 'ok' | 'error' | 'info'
  title: string
  text?: string
  action?: ToastAction
}

let seq = 0
export const toasts = reactive<Toast[]>([])

export function dismiss(id: number) {
  const i = toasts.findIndex(t => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

/** toast('标题') / toast('标题', 'ok') / toast({ title, text, action, kind }) */
export function toast(input: string | Omit<Toast, 'id'>, kind: Toast['kind'] = 'info') {
  const id = ++seq
  const t: Toast = typeof input === 'string' ? { id, kind, title: input } : { ...input, id }
  toasts.push(t)
  if (toasts.length > 4) toasts.splice(0, toasts.length - 4)
  setTimeout(() => dismiss(id), t.kind === 'error' ? 8000 : t.action ? 7000 : 4000)
}

export function toastError(e: unknown, title = '操作失败') {
  toast({ kind: 'error', title, text: (e as any)?.message ?? String(e) })
}
