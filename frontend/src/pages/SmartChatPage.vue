<template>
  <div class="smart-chat-page">
    <!-- Sidebar - capability rail -->
    <aside class="sidebar" :class="{ collapsed: mobileMenuOpen }">
      <button class="new-chat-btn" @click="resetChat">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        <span>新会话</span>
      </button>

      <div class="sidebar-section">
        <span class="section-label">数据源</span>
        <button
          v-for="item in dataSourceActions"
          :key="item.title"
          class="quick-action"
          @click="sendQuickAction(item.text)"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path :d="item.iconPath"/>
          </svg>
          <span>{{ item.title }}</span>
        </button>
      </div>

      <div class="sidebar-section">
        <span class="section-label">快捷操作</span>
        <button
          v-for="item in quickActions"
          :key="item.title"
          class="quick-action"
          @click="sendQuickAction(item.text)"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path :d="item.iconPath"/>
          </svg>
          <span>{{ item.title }}</span>
        </button>
      </div>

      <div class="sidebar-footer">
        <div class="status-card">
          <div class="status-dot" :class="{ online: capabilitiesOnline > 0 }"></div>
          <span>{{ capabilitiesOnline }}/{{ totalCapabilities }} 能力就绪</span>
        </div>
      </div>
    </aside>

    <!-- Mobile menu toggle -->
    <button class="mobile-menu-btn" @click="mobileMenuOpen = !mobileMenuOpen">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="3" y1="6" x2="21" y2="6"/>
        <line x1="3" y1="12" x2="21" y2="12"/>
        <line x1="3" y1="18" x2="21" y2="18"/>
      </svg>
    </button>

    <!-- Main area -->
    <main class="main-area">
      <!-- Header -->
      <header class="chat-header">
        <div class="header-title">
          <strong>DataWorks Agent</strong>
          <span class="header-badge">Workspace</span>
        </div>
        <div class="header-actions">
          <span class="conn-status" :class="{ online: isConnected }">
            <span class="conn-dot"></span>
            {{ isConnected ? '实时' : 'HTTP' }}
          </span>
          <button class="refresh-btn" @click="loadCapabilities">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="23 4 23 10 17 10"/>
              <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>
            </svg>
          </button>
        </div>
      </header>

      <!-- Messages area -->
      <div ref="messagesContainer" class="messages-container">
        <!-- Welcome state -->
        <WelcomePanel v-if="messages.length === 0" @select="handlePromptSelect" />

        <!-- Message list -->
        <div v-else class="messages-list">
          <MessageBubble
            v-for="msg in messages"
            :key="msg.id"
            :role="msg.role"
            :content="msg.content"
            :streaming="msg.streaming"
            :option-chips="msg.optionChips"
            @pick="handleSend"
          />
        </div>
      </div>

      <!-- Composer -->
      <Composer
        :disabled="isStreaming"
        :placeholder="messages.length === 0 ? '描述你想做什么，例如：从OSS数据源建全链路数仓...' : '继续对话...'"
        @send="handleSend"
      />
    </main>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import MessageBubble from '@/components/agent/MessageBubble.vue'
import Composer from '@/components/agent/Composer.vue'
import WelcomePanel from '@/components/agent/WelcomePanel.vue'
import { createSSEStream, type SSEEvent } from '@/utils/sse-client'
import { idempotencyKey } from '@/utils/request'

interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  optionChips?: Array<{
    id: string
    type: 'pick_table' | 'free_text'
    label: string
    subtitle?: string
    layer?: string
    value?: string
    placeholder?: string
  }>
}

const messages = ref<ChatMessage[]>([])
const messagesContainer = ref<HTMLElement>()
const conversationId = ref<string>(idempotencyKey())
const isStreaming = ref(false)
const isConnected = ref(false)
const mobileMenuOpen = ref(false)
const capabilitiesOnline = ref(0)
const totalCapabilities = ref(0)

// Data source quick actions
const dataSourceActions = [
  {
    title: 'OSS 数据入仓',
    text: '请帮我搭建从 OSS 数据源到 DWS 汇总的全链路建模，数据路径是 oss://bucket/data/orders.json，文件格式是 JSON。',
    iconPath: 'M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z',
  },
  {
    title: 'Holo 数据入仓',
    text: '请帮我搭建从 Hologres 数据源到 DWD 明细的全链路建模，schema 是 public，表名是 orders。',
    iconPath: 'M4 7V4a2 2 0 0 1 2-2h8.5L20 7.5V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3',
  },
  {
    title: 'MySQL 数据入仓',
    text: '请帮我搭建从 MySQL 数据源到 DWS 汇总的全链路建模，数据源名是 jky_singleshop，表名是 orders。',
    iconPath: 'M12 2L2 7l10 5 10-5-10-5z',
  },
]

// Quick actions
const quickActions = [
  { title: '全链路建模', text: '请帮我搭建从 ads_data 到 dw_order 的 ODS、DWD、DIM、DWS 全链路建模', iconPath: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' },
  { title: '智能问数', text: '请帮我查询订单表的数据量，并按日期统计', iconPath: 'M3 3v18h18M18 17l-6-6-4 4' },
  { title: '异常排查', text: '请排查 DataWorks 中某节点的失败原因', iconPath: 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01' },
  { title: 'Cookie 管理', text: '查看当前 Cookie 和 AK/SK 的连接状态', iconPath: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' },
]

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function resetChat() {
  conversationId.value = idempotencyKey()
  messages.value = []
  isStreaming.value = false
}

function sendQuickAction(text: string) {
  handleSend(text)
}

function handlePromptSelect(text: string) {
  handleSend(text)
}

async function handleSend(text: string) {
  if (!text.trim() || isStreaming.value) return

  // Add user message
  messages.value.push({
    id: idempotencyKey(),
    role: 'user',
    content: text,
  })

  await nextTick(scrollToBottom)

  // Create assistant placeholder for streaming
  const assistantMsgId = idempotencyKey()
  messages.value.push({
    id: assistantMsgId,
    role: 'assistant',
    content: '',
    streaming: true,
  })

  isStreaming.value = true

  // Start SSE stream
  const controller = createSSEStream(text, {
    conversationId: conversationId.value,
    executionMode: 'auto',
    onEvent: (event: SSEEvent) => {
      if (event.type === 'connected') {
        isConnected.value = true
        conversationId.value = event.conversation_id
      } else if (event.type === 'thinking') {
        // Update streaming message with thinking text
        const idx = messages.value.findIndex(m => m.id === assistantMsgId)
        if (idx >= 0) {
          messages.value[idx].content = event.message
        }
      } else if (event.type === 'response') {
        // Replace streaming message with full response
        const idx = messages.value.findIndex(m => m.id === assistantMsgId)
        if (idx >= 0) {
          messages.value[idx] = {
            id: assistantMsgId,
            role: 'assistant',
            content: event.message,
            streaming: false,
            optionChips: event.data?.option_chips,
          }
        }
        isStreaming.value = false
        nextTick(scrollToBottom)
      } else if (event.type === 'error') {
        const idx = messages.value.findIndex(m => m.id === assistantMsgId)
        if (idx >= 0) {
          messages.value[idx] = {
            id: assistantMsgId,
            role: 'assistant',
            content: `❌ ${event.message}`,
            streaming: false,
          }
        }
        isStreaming.value = false
        nextTick(scrollToBottom)
      }
    },
    onError: (err: Error) => {
      const idx = messages.value.findIndex(m => m.id === assistantMsgId)
      if (idx >= 0) {
        messages.value[idx] = {
          id: assistantMsgId,
          role: 'assistant',
          content: `❌ 连接失败: ${err.message}`,
          streaming: false,
        }
      }
      isStreaming.value = false
      nextTick(scrollToBottom)
    },
  })

  // Cleanup on unmount
  onUnmounted(() => controller.abort())
}

async function loadCapabilities() {
  try {
    const resp = await fetch('/agent/capabilities')
    const data = await resp.json()
    const caps = data.capabilities || {}
    totalCapabilities.value = Object.keys(caps).length
    capabilitiesOnline.value = Object.values(caps).filter((v: any) => v.online !== false).length
  } catch {
    // Keep existing values
  }
}

onMounted(() => {
  loadCapabilities()
})
</script>

<style scoped>
.smart-chat-page {
  height: calc(100vh - var(--topbar-height) - var(--page-padding));
  min-height: 0;
  display: grid;
  grid-template-columns: 220px 1fr;
  overflow: hidden;
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-primary);
}

/* Sidebar */
.sidebar {
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
  border-right: 1px solid var(--color-border-primary);
  background: var(--color-bg-secondary);
  transition: transform 0.3s ease;
  overflow-y: auto;
}

.sidebar.collapsed {
  display: none;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 40px;
  border: 1.5px solid var(--color-border-primary);
  border-radius: 10px;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  font-weight: 600;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.new-chat-btn:hover {
  border-color: #6366F1;
  color: #6366F1;
  background: rgba(99, 102, 241, 0.05);
}

.new-chat-btn svg {
  width: 16px;
  height: 16px;
}

.sidebar-section {
  margin-top: 20px;
}

.section-label {
  display: block;
  padding: 0 8px 8px;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.quick-action {
  width: 100%;
  height: 36px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}

.quick-action:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.quick-action svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  opacity: 0.6;
}

.sidebar-footer {
  margin-top: auto;
  padding-top: 16px;
}

.status-card {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 10px;
  background: var(--color-bg-tertiary);
  font-size: 11px;
  color: var(--color-text-tertiary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
}

.status-dot.online {
  background: #22C55E;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.15);
}

/* Mobile menu */
.mobile-menu-btn {
  display: none;
  position: fixed;
  top: calc(var(--topbar-height) + 8px);
  left: 8px;
  z-index: 100;
  width: 40px;
  height: 40px;
  border: 1px solid var(--color-border-primary);
  border-radius: 10px;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  cursor: pointer;
  place-items: center;
}

.mobile-menu-btn svg {
  width: 20px;
  height: 20px;
}

/* Main area */
.main-area {
  min-width: 0;
  min-height: 0;
  display: grid;
  grid-template-rows: 56px minmax(0, 1fr) auto;
  background: var(--color-bg-primary);
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid var(--color-border-primary);
}

.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-title strong {
  color: var(--color-text-primary);
  font-size: 15px;
  font-weight: 700;
}

.header-badge {
  padding: 2px 8px;
  border-radius: 6px;
  background: rgba(99, 102, 241, 0.08);
  color: #6366F1;
  font-size: 11px;
  font-weight: 700;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.conn-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--color-border-primary);
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.conn-status .conn-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #F59E0B;
}

.conn-status.online .conn-dot {
  background: #22C55E;
}

.refresh-btn {
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all 0.15s;
}

.refresh-btn:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
}

.refresh-btn svg {
  width: 16px;
  height: 16px;
}

/* Messages */
.messages-container {
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.messages-list {
  padding: 24px;
}

/* Responsive */
@media (max-width: 768px) {
  .smart-chat-page {
    grid-template-columns: 1fr;
    border-radius: 0;
    border: none;
  }

  .sidebar {
    position: fixed;
    top: var(--topbar-height);
    left: 0;
    bottom: 0;
    width: 260px;
    z-index: 99;
    box-shadow: 4px 0 20px rgba(0, 0, 0, 0.15);
  }

  .sidebar.collapsed {
    transform: translateX(-100%);
  }

  .mobile-menu-btn {
    display: grid;
  }

  .messages-list {
    padding: 16px;
  }

  .chat-header {
    padding: 0 16px;
  }
}
</style>
