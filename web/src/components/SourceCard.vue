<template>
  <article class="source-card" :class="{ 'is-active': active }">
    <div class="head">
      <span class="clause-no">{{ citation.clause_no || '条款' }}</span>
      <span class="file">{{ citation.file_title }}</span>
      <span v-if="citation.consistent" class="consistent">引用一致</span>
    </div>
    <div class="excerpt">{{ citation.excerpt }}</div>
    <div class="source-footer"><span>{{ citation.source_page ? `原文第 ${citation.source_page} 页` : (citation.regulation_code || '制度原文') }}</span><button type="button" @click.stop="open">查看完整条款</button></div>
  </article>
</template>

<script setup lang="ts">
import type { Citation } from '@/api/qa'

const props = defineProps<{ citation: Citation; active?: boolean }>()
const emit = defineEmits<{ (e: 'open', id: string): void }>()

function open() {
  emit('open', props.citation.clause_id)
}
</script>

<style scoped>
.source-card { padding: 9px 10px; margin-bottom: 8px; border: 1px solid var(--zg-border); background: #fff; scroll-margin-top: 12px; transition: border-color .15s, box-shadow .15s, background .15s; }
.source-card:hover { border-color: #94b4cd; background: #f8fbfd; }
.source-card.is-active { border-color: #2F80ED; background: #f2f8ff; box-shadow: 0 0 0 2px rgba(47, 128, 237, .16); }
.head { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
.clause-no { flex-shrink: 0; color: var(--zg-primary); font-size: 12px; }
.file { overflow: hidden; color: var(--zg-text); font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.consistent { flex-shrink: 0; margin-left: auto; color: #4d8b66; font-size: 11px; }
.excerpt { color: var(--zg-text-secondary); font-size: 12px; line-height: 1.7; white-space: pre-wrap; max-height: 180px; overflow: auto; }
.source-footer { display: flex; align-items: center; justify-content: space-between; margin-top: 7px; padding-top: 6px; border-top: 1px solid var(--zg-border-light); color: var(--zg-text-weak); font-size: 11px; }.source-footer button { padding: 0; border: 0; color: var(--zg-primary); background: transparent; cursor: pointer; font: inherit; font-size: 12px; }.source-footer button:hover { text-decoration: underline; }
</style>
