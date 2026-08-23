<script setup lang="ts">
import { computed } from 'vue'
import { renderSafeMarkdown } from '@/utils/safeMarkdown'

const props = withDefaults(defineProps<{
  content?: string
}>(), {
  content: '',
})

const renderedContent = computed(() => renderSafeMarkdown(props.content))
</script>

<template>
  <div class="markdown-content" v-html="renderedContent" />
</template>

<style scoped>
.markdown-content {
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  overflow-x: auto;
  color: var(--ots-text-primary);
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) {
  margin: 14px 0 8px;
  line-height: 1.4;
  font-weight: 650;
}
.markdown-content :deep(h1) { font-size: 18px; }
.markdown-content :deep(h2) { font-size: 16px; }
.markdown-content :deep(h3),
.markdown-content :deep(h4),
.markdown-content :deep(h5),
.markdown-content :deep(h6) { font-size: 14px; }
.markdown-content :deep(p) { margin: 7px 0; }
.markdown-content :deep(ul),
.markdown-content :deep(ol) { margin: 7px 0; padding-left: 24px; }
.markdown-content :deep(li) { margin: 3px 0; }
.markdown-content :deep(pre) {
  margin: 10px 0;
  padding: 10px 12px;
  overflow-x: auto;
  border-radius: 6px;
  background: #f4f6f8;
  border: 1px solid var(--ots-border);
}
.markdown-content :deep(code) {
  padding: 1px 4px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.06);
  font-family: 'Cascadia Code', Consolas, monospace;
  font-size: 0.92em;
}
.markdown-content :deep(pre code) { padding: 0; background: transparent; }
.markdown-content :deep(blockquote) {
  margin: 10px 0;
  padding-left: 12px;
  border-left: 3px solid var(--ots-primary);
  color: var(--ots-text-secondary);
}
.markdown-content :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  margin: 10px 0;
  overflow-x: auto;
  border-collapse: collapse;
}
.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 6px 10px;
  border: 1px solid var(--ots-border);
  vertical-align: top;
}
.markdown-content :deep(th) { background: var(--ots-bg); font-weight: 600; }
.markdown-content :deep(a) { color: var(--ots-primary); }
</style>
