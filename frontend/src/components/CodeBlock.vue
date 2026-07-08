<template>
  <pre class="code-block" :style="computedStyle"><slot /></pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  maxHeight?: string | number
}

const props = withDefaults(defineProps<Props>(), {
  maxHeight: '400px',
})

const computedStyle = computed(() => ({
  maxHeight: typeof props.maxHeight === 'number' ? `${props.maxHeight}px` : props.maxHeight,
}))
</script>

<style scoped>
.code-block {
  margin: 0;
  padding: 10px 14px;
  background: #1e1e2e;
  border: 1px solid #313240;
  border-radius: 6px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #cdd6f4;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-y: auto;
}
.code-block::-webkit-scrollbar {
  width: 6px;
}
.code-block::-webkit-scrollbar-thumb {
  background: #45475a;
  border-radius: 3px;
}
.code-block::-webkit-scrollbar-track {
  background: transparent;
}
</style>
