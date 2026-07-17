<template>
  <div class="composer">
    <div class="composer-container" :class="{ focused: isFocused }">
      <textarea
        ref="textareaRef"
        v-model="inputText"
        :placeholder="placeholder"
        :disabled="disabled"
        rows="1"
        @keydown.enter.exact.prevent="handleSend"
        @focus="isFocused = true"
        @blur="isFocused = false"
        @input="autoResize"
      />
      <button
        class="send-btn"
        :disabled="!canSend || disabled"
        @click="handleSend"
      >
        <svg v-if="!disabled" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <line x1="22" y1="2" x2="11" y2="13"/>
          <polygon points="22 2 15 22 11 13 2 9 22 2"/>
        </svg>
        <svg v-else class="spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
      </button>
    </div>
    <div class="composer-footer">
      <span class="hint">Enter 发送 · Shift+Enter 换行</span>
      <span class="mode-badge" :class="mode">{{ modeLabel }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

interface Props {
  disabled?: boolean
  placeholder?: string
  mode?: 'auto' | 'plan' | 'dev_execute'
}

const props = withDefaults(defineProps<Props>(), {
  disabled: false,
  placeholder: '输入消息，或点击左侧快捷操作...',
  mode: 'auto',
})

const emit = defineEmits<{
  send: [message: string]
}>()

const inputText = ref('')
const isFocused = ref(false)
const textareaRef = ref<HTMLTextAreaElement>()

const canSend = computed(() => inputText.value.trim().length > 0 && !props.disabled)

const modeLabel = computed(() => {
  const labels: Record<string, string> = {
    auto: '自动',
    plan: '仅规划',
    dev_execute: '执行',
  }
  return labels[props.mode] ?? '自动'
})

function handleSend() {
  if (!canSend.value) return
  const text = inputText.value.trim()
  inputText.value = ''
  emit('send', text)
  nextTick(() => autoResize())
}

function autoResize() {
  if (!textareaRef.value) return
  const el = textareaRef.value
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}
</script>

<style scoped>
.composer {
  padding: 0 var(--space-5);
  padding-bottom: var(--space-4);
}

.composer-container {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 8px 12px;
  border: 1.5px solid var(--color-border-primary);
  border-radius: 16px;
  background: var(--color-bg-secondary);
  transition: border-color 0.2s, box-shadow 0.2s;
}

.composer-container.focused {
  border-color: #6366F1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.composer-container textarea {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  resize: none;
  padding: 6px 4px;
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  color: var(--color-text-primary);
  max-height: 160px;
}

.composer-container textarea::placeholder {
  color: var(--color-text-tertiary);
}

.send-btn {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: transform 0.15s, opacity 0.15s;
}

.send-btn:hover:not(:disabled) {
  transform: scale(1.05);
}

.send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-btn svg {
  width: 18px;
  height: 18px;
}

.send-btn .spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.composer-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
  padding: 0 4px;
}

.hint {
  font-size: 11px;
  color: var(--color-text-tertiary);
}

.mode-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}

.mode-badge.auto {
  background: rgba(99, 102, 241, 0.1);
  color: #6366F1;
}

.mode-badge.plan {
  background: rgba(251, 191, 36, 0.1);
  color: #F59E0B;
}

.mode-badge.dev_execute {
  background: rgba(239, 68, 68, 0.1);
  color: #EF4444;
}
</style>
