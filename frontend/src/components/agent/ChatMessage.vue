<template>
  <div class="chat-message" :class="{ 'user-message': message.isUser }">
    <div class="message-avatar">
      <el-avatar :size="32" :icon="message.isUser ? 'User' : 'Monitor'" />
    </div>
    <div class="message-content">
      <div class="message-text" v-html="renderedText" />
      <div class="message-time">{{ formatTime(message.timestamp) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

interface Message {
  id: string
  text: string
  isUser: boolean
  timestamp: Date
}

const props = defineProps<{
  message: Message
}>()

const md = new MarkdownIt({ breaks: true })

const renderedText = computed(() => {
  if (props.message.isUser) return props.message.text
  const html = md.render(props.message.text)
  return DOMPurify.sanitize(html)
})

function formatTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.user-message {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 70%;
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  background: #f0f0f0;
  line-height: 1.6;
}

.message-text :deep(p) {
  margin: 0 0 8px;
}

.message-text :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.message-text :deep(pre) {
  margin: 8px 0;
  padding: 12px;
  background: #1e1e2e;
  border-radius: 6px;
  overflow-x: auto;
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
  color: #cdd6f4;
}

.user-message .message-text {
  background: #409eff;
  color: white;
}

.message-time {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

.user-message .message-time {
  text-align: right;
}
</style>
