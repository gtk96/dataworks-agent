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
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  font-weight: 800;
  font-size: 11px;
}
.user-avatar {
  background: #1E293B;
  color: #fff;
  font-weight: 800;
  font-size: 11px;
}

.message-content {
  max-width: min(76%, 780px);
}

.message-author {
  margin: 0 0 4px 2px;
  color: #94A3B8;
  font-size: 11px;
  font-weight: 600;
}

.user-message .message-author,
.user-message .message-time {
  text-align: right;
}

.message-text {
  padding: 11px 14px;
  border-radius: 14px;
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  color: #1E293B;
  line-height: 1.65;
  font-size: 13px;
}

.user-message .message-text {
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  border-color: transparent;
  color: #fff;
}

.message-text :deep(p) {
  margin: 0 0 6px;
}

.message-text :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text :deep(code) {
  background: rgba(99, 102, 241, 0.1);
  padding: 1px 5px;
  border-radius: 4px;
  color: #4F46E5;
  font-size: 0.9em;
}

.user-message .message-text :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.message-text :deep(pre) {
  margin: 8px 0;
  padding: 10px;
  background: #0F172A;
  border-radius: 8px;
  overflow-x: auto;
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
  color: #E2E8F0;
  font-size: 0.85em;
}

.message-time {
  margin-top: 4px;
  color: #94A3B8;
  font-size: 10px;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
