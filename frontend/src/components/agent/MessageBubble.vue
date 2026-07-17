<template>
  <div class="message-bubble" :class="[role, { streaming }]">
    <div class="avatar">
      <div v-if="role === 'user'" class="avatar-user">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
          <circle cx="12" cy="7" r="4"/>
        </svg>
      </div>
      <div v-else class="avatar-agent">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L2 7l10 5 10-5-10-5z"/>
          <path d="M2 17l10 5 10-5"/>
          <path d="M2 12l10 5 10-5"/>
        </svg>
      </div>
    </div>
    <div class="bubble-wrapper">
      <div class="bubble" v-html="renderedContent" />
      <div v-if="streaming" class="streaming-indicator">
        <span class="dot"></span>
        <span class="dot"></span>
        <span class="dot"></span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown-render'

interface Props {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
}

const props = defineProps<Props>()

const renderedContent = computed(() => {
  if (props.role === 'user') {
    // User messages: escape HTML, preserve line breaks
    const escaped = props.content
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/\n/g, '<br>')
    return escaped
  }
  return renderMarkdown(props.content).html
})
</script>

<style scoped>
.message-bubble {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  align-items: flex-start;
}

.message-bubble.user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  display: grid;
  place-items: center;
}

.avatar-user {
  background: #1E293B;
  color: #94A3B8;
}

.avatar-user svg {
  width: 18px;
  height: 18px;
}

.avatar-agent {
  background: linear-gradient(135deg, #6366F1, #8B5CF6);
  color: #fff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.avatar-agent svg {
  width: 18px;
  height: 18px;
}

.bubble-wrapper {
  max-width: min(75%, 720px);
  min-width: 0;
}

.bubble {
  padding: 12px 16px;
  border-radius: 16px;
  line-height: 1.65;
  font-size: 14px;
  word-break: break-word;
}

.message-bubble.user .bubble {
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-bubble.assistant .bubble {
  background: #F1F5F9;
  color: #1E293B;
  border: 1px solid #E2E8F0;
  border-bottom-left-radius: 4px;
}

/* Markdown styles inside assistant bubbles */
.bubble :deep(h1), .bubble :deep(h2), .bubble :deep(h3) {
  margin: 12px 0 6px;
  font-weight: 600;
}

.bubble :deep(h1) { font-size: 1.3em; }
.bubble :deep(h2) { font-size: 1.15em; }
.bubble :deep(h3) { font-size: 1.05em; }

.bubble :deep(p) {
  margin: 0 0 8px;
}

.bubble :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble :deep(code) {
  background: rgba(99, 102, 241, 0.1);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  color: #4F46E5;
}

.message-bubble.user :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.bubble :deep(pre) {
  margin: 10px 0;
  padding: 12px 14px;
  background: #0F172A;
  border-radius: 10px;
  overflow-x: auto;
  border: 1px solid #1E293B;
}

.bubble :deep(pre code) {
  background: none;
  padding: 0;
  color: #E2E8F0;
  font-size: 0.85em;
  line-height: 1.5;
}

.bubble :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 13px;
}

.bubble :deep(th), .bubble :deep(td) {
  padding: 8px 12px;
  border: 1px solid #CBD5E1;
  text-align: left;
}

.bubble :deep(th) {
  background: #F8FAFC;
  font-weight: 600;
}

.bubble :deep(ul), .bubble :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.bubble :deep(li) {
  margin-bottom: 4px;
}

.bubble :deep(blockquote) {
  margin: 8px 0;
  padding: 8px 14px;
  border-left: 3px solid #6366F1;
  background: rgba(99, 102, 241, 0.05);
  color: #475569;
}

.bubble :deep(a) {
  color: #6366F1;
  text-decoration: underline;
}

.message-bubble.user :deep(a) {
  color: #C7D2FE;
}

/* Streaming indicator */
.streaming-indicator {
  display: flex;
  gap: 4px;
  padding: 4px 0 0 4px;
}

.streaming-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #6366F1;
  animation: pulse 1.2s ease-in-out infinite;
}

.streaming-indicator .dot:nth-child(2) {
  animation-delay: 0.2s;
}

.streaming-indicator .dot:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes pulse {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* Empty message */
.empty-message {
  height: 2px;
}
</style>
