<template>
  <div class="chat-message" :class="{ 'user-message': message.isUser }">
    <div class="message-avatar">
      <el-avatar :size="34" :class="message.isUser ? 'user-avatar' : 'agent-avatar'">
        {{ message.isUser ? '我' : 'AI' }}
      </el-avatar>
    </div>
    <div class="message-content">
      <div class="message-author">{{ message.isUser ? '你' : 'DataWorks Agent' }}</div>
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
  if (props.message.isUser) return DOMPurify.sanitize(props.message.text)
  return DOMPurify.sanitize(md.render(props.message.text))
})

function formatTime(date: Date): string {
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
}

.user-message {
  flex-direction: row-reverse;
}

.message-avatar {
  flex: 0 0 auto;
}

.agent-avatar {
  background: linear-gradient(135deg, #2456d6, #4f8cff);
  color: #fff;
  font-weight: 800;
}

.user-avatar {
  background: #111827;
  color: #fff;
  font-weight: 800;
}

.message-content {
  max-width: min(76%, 780px);
}

.message-author {
  margin: 0 0 5px 2px;
  color: #98a2b3;
  font-size: 12px;
  font-weight: 700;
}

.user-message .message-author,
.user-message .message-time {
  text-align: right;
}

.message-text {
  padding: 13px 16px;
  border: 1px solid rgba(98, 128, 210, 0.12);
  border-radius: 18px;
  background: #ffffff;
  color: #26324b;
  line-height: 1.7;
  box-shadow: 0 10px 26px rgba(31, 45, 91, 0.07);
}

.user-message .message-text {
  border-color: rgba(64, 158, 255, 0.35);
  background: linear-gradient(135deg, #2456d6, #409eff);
  color: #fff;
}

.message-text :deep(p) {
  margin: 0 0 8px;
}

.message-text :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text :deep(code) {
  background: rgba(36, 86, 214, 0.08);
  padding: 2px 6px;
  border-radius: 6px;
  color: #1d4ed8;
  font-size: 0.9em;
}

.user-message .message-text :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.message-text :deep(pre) {
  margin: 10px 0;
  padding: 12px;
  background: #111827;
  border-radius: 10px;
  overflow-x: auto;
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
  color: #e5e7eb;
}

.message-time {
  margin-top: 5px;
  color: #98a2b3;
  font-size: 12px;
}
</style>
