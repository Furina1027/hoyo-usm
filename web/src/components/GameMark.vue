<script setup lang="ts">
/** 游戏标记：带主题色的圆角方块 + 单字。 */
import { GAME_META, type GameId } from '../api'

withDefaults(defineProps<{ game: GameId | string, size?: number }>(), { size: 28 })
</script>

<template>
  <span
    class="inline-flex items-center justify-center shrink-0 font-bold rounded-[28%]"
    :style="{
      width: `${size}px`, height: `${size}px`, fontSize: `${size * 0.46}px`,
      color: GAME_META[game as GameId]?.color,
      background: `color-mix(in oklab, ${GAME_META[game as GameId]?.color} 16%, transparent)`,
      boxShadow: `inset 0 0 0 1px color-mix(in oklab, ${GAME_META[game as GameId]?.color} 30%, transparent)`,
    }"
  >{{ GAME_META[game as GameId]?.short ?? '?' }}</span>
</template>
