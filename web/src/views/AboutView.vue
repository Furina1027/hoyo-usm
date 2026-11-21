<script setup lang="ts">
import { Clapperboard, ShieldAlert, Scale, HelpCircle, Keyboard } from 'lucide-vue-next'

const version = __APP_VERSION__

const faq = [
  { q: '导出时提示“缺密钥”', a: '这个文件的密钥还没有收录。到设置 → 密钥库填写更新源并点“立即更新”，或者等上游收录后再更新。' },
  { q: '找不到游戏目录', a: '到设置 → 游戏目录，选择包含游戏主程序（YuanShen.exe / StarRail.exe / ZenlessZoneZero.exe）的文件夹。' },
  { q: '外部文件识别失败', a: '少数文件在游戏里有同名但密钥不同的版本，离开游戏目录后无法区分。请把文件放回原目录，在“游戏文件”页导出。' },
  { q: '绝区零导出没有声音', a: '绝区零的过场动画文件本身不含音频（声音在别的资源里），导出纯视频是正常的。' },
  { q: '导出的视频比原文件大', a: '音频从 HCA/ADX 解码成了无损 FLAC/WAV。想要更小的文件可以在导出时选 AAC。' },
]

const keys = [
  ['Ctrl + 1…5', '切换页面'],
  ['/ 或 Ctrl + F', '搜索文件'],
  ['↑ ↓', '在文件列表中移动'],
  ['Enter', '查看文件详情'],
  ['Space', '勾选 / 取消勾选'],
  ['Shift + 点击', '连续勾选'],
  ['Ctrl + A', '全选当前列表'],
  ['Ctrl + E', '导出已选'],
  ['Esc', '关闭详情 / 清除勾选'],
]
</script>

<template>
  <div class="h-full overflow-auto">
    <div class="max-w-[880px] mx-auto px-8 py-7 space-y-5">
      <section class="card p-7 flex items-center gap-5">
        <div class="h-16 w-16 rounded-[20px] bg-gradient-to-br from-accent-2 to-accent flex items-center justify-center shadow-[0_10px_30px_-10px_var(--c-accent)]">
          <Clapperboard class="w-8 h-8 text-white" />
        </div>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight">hoyo-usm <span class="text-base text-fg-3 font-normal">v{{ version }}</span></h1>
          <p class="mt-1 text-sm text-fg-2 leading-6">
            原神 / 星穹铁道 / 绝区零过场动画（CRI USM）无损解密导出工具。视频流原样复制，音频解码后无损封装。
          </p>
        </div>
      </section>

      <div class="grid grid-cols-2 gap-5">
        <section class="card p-6">
          <h2 class="font-semibold flex items-center gap-2"><HelpCircle class="w-4 h-4 text-accent" />常见问题</h2>
          <dl class="mt-4 space-y-4 text-sm">
            <div v-for="f in faq" :key="f.q">
              <dt class="font-medium">{{ f.q }}</dt>
              <dd class="mt-1 text-fg-3 leading-6">{{ f.a }}</dd>
            </div>
          </dl>
        </section>

        <div class="space-y-5">
          <section class="card p-6">
            <h2 class="font-semibold flex items-center gap-2"><Keyboard class="w-4 h-4 text-accent" />快捷键</h2>
            <ul class="mt-4 space-y-2 text-sm">
              <li v-for="[k, d] in keys" :key="k" class="flex items-center">
                <span class="text-fg-2">{{ d }}</span>
                <span class="ml-auto flex gap-1">
                  <span v-for="part in k.split(' ')" :key="part" :class="part === '+' || part === '或' || part === '…' ? 'text-fg-3 text-xs px-0.5' : 'kbd'">{{ part }}</span>
                </span>
              </li>
            </ul>
          </section>

          <section class="card p-6 border-warn/30">
            <h2 class="font-semibold flex items-center gap-2"><ShieldAlert class="w-4 h-4 text-warn" />免责声明</h2>
            <ul class="mt-3 text-sm text-fg-2 leading-6 list-disc pl-5 space-y-1">
              <li>仅供个人学习与观看，请勿传播导出内容或用于商业用途</li>
              <li>与 miHoYo / HoYoverse 无任何关联，只处理你本机已有的游戏文件</li>
              <li>密钥来自社区公开维护的快照，本项目不含破解逻辑</li>
            </ul>
          </section>

          <section class="card p-6">
            <h2 class="font-semibold flex items-center gap-2"><Scale class="w-4 h-4 text-fg-3" />开源许可</h2>
            <ul class="mt-3 text-sm text-fg-3 leading-6 space-y-1">
              <li>hoyo-usm：MIT License</li>
              <li>ffmpeg（随包附带）：GPL / LGPL</li>
              <li>cricodecs、numpy、pycryptodome、FastAPI、Vue、reka-ui 等依各自许可证分发</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  </div>
</template>
