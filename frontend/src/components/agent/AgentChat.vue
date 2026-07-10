<template>
  <div class="agent-chat">
    <div class="chat-messages" ref="messagesRef">
      <ChatMessage
        v-for="msg in messages"
        :key="msg.id"
        :message="msg"
      />
      <div v-if="loading" class="typing-indicator">
        <span /><span /><span />
      </div>
    </div>

    <QuickActions @action="handleQuickAction" />

    <div class="chat-input">
      <el-input
        v-model="input"
        placeholder="描述您的需求..."
        :disabled="loading"
        @keyup.enter="sendMessage"
      >
        <template #append>
          <el-button @click="sendMessage" :loading="loading" :disabled="!input.trim()">
            发送
          </el-button>
        </template>
      </el-input>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { request } from '@/utils/request'
import ChatMessage from './ChatMessage.vue'
import QuickActions from './QuickActions.vue'

interface ChatMsg {
  id: string
  text: string
  isUser: boolean
  timestamp: Date
}

const input = ref('')
const loading = ref(false)
const messages = ref<ChatMsg[]>([])
const messagesRef = ref<HTMLElement>()

onMounted(() => {
  messages.value.push({
    id: 'welcome',
    text: '您好！我是数仓助手，可以帮您创建表、查询血缘、检查任务状态等。请问有什么可以帮您？',
    isUser: false,
    timestamp: new Date(),
  })
})

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return

  input.value = ''
  messages.value.push({
    id: Date.now().toString(),
    text,
    isUser: true,
    timestamp: new Date(),
  })

  await nextTick()
  scrollToBottom()

  loading.value = true
  try {
    const data = await request<{ message: string }>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text }),
    })
    messages.value.push({
      id: (Date.now() + 1).toString(),
      text: data.message,
      isUser: false,
      timestamp: new Date(),
    })
  } catch {
    messages.value.push({
      id: (Date.now() + 1).toString(),
      text: '抱歉，请求失败，请稍后重试。',
      isUser: false,
      timestamp: new Date(),
    })
  } finally {
    loading.value = false
    await nextTick()
    scrollToBottom()
  }
}

function handleQuickAction(prompt: string) {
  input.value = prompt
  sendMessage()
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}
</script>

<style scoped>
.agent-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: #f0f0f0;
  border-radius: 12px;
  width: fit-content;
  margin-bottom: 16px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: #999;
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

.chat-input {
  padding: 12px;
  border-top: 1px solid #eee;
}
</style>
