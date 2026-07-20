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
      <!-- Header with tabs -->
      <header class="chat-header">
        <div class="header-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="tab-btn"
            :class="{ active: activeTab === tab.key }"
            @click="activeTab = tab.key"
          >
            <svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path v-if="tab.icon === 'chat'" d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              <path v-else d="M3 3v18h18M18 17l-6-6-4 4"/>
            </svg>
            <span>{{ tab.label }}</span>
          </button>
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
        <WelcomePanel v-if="messages.length === 0 && activeTab === 'chat'" @select="handlePromptSelect" />

        <!-- Cookie management view -->
        <div v-else-if="activeTab === 'cookie'" class="cookie-view">
          <div class="cookie-header">
            <h2>Cookie 与执行底座</h2>
            <p>检查 AK/SK、Cookie BFF、CDP 9222 和官方 MCP 的连接状态</p>
          </div>
          <div class="cookie-grid">
            <div
              v-for="(cap, key) in capabilityStatus"
              :key="key"
              class="cap-card"
              :class="{ online: cap.online }"
            >
              <div class="cap-icon" :class="{ online: cap.online }">
                {{ cap.online ? '✓' : '○' }}
              </div>
              <div class="cap-info">
                <strong>{{ cap.label }}</strong>
                <span>{{ cap.status }}</span>
              </div>
            </div>
          </div>
          <button class="refresh-cookie-btn" :disabled="loadingCookie" @click="refreshCookieStatus">
            {{ loadingCookie ? '刷新中...' : '刷新状态' }}
          </button>
        </div>

        <!-- Chat view -->
        <template v-else>
          <!-- Message list -->
          <div v-if="messages.length > 0" class="messages-list">
            <MessageBubble
              v-for="msg in messages"
              :key="msg.id"
              :role="msg.role"
              :content="msg.content"
              :streaming="msg.streaming"
              :option-chips="msg.optionChips"
              :interaction="msg.interaction"
              :active-interaction-id="activeInteractionId"
              @pick="handleSend"
              @answer-interaction="handleInteractionAnswer"
            />
          </div>

          <!-- Result card (shown after agent response) -->
          <article v-if="lastPayload" class="result-card">
            <header class="result-header">
              <div>
                <span class="result-kicker">EXECUTION SUMMARY</span>
                <h3>{{ resultTitle }}</h3>
              </div>
              <span class="result-state" :class="agentMode">{{ modeText }}</span>
            </header>

            <div class="result-metrics">
              <div><strong>{{ stepMetricValue }}</strong><span>步骤</span></div>
              <div><strong>{{ artifactCount }}</strong><span>产物</span></div>
              <div><strong>{{ tableCount }}</strong><span>表/节点</span></div>
              <div><strong>{{ publishGateText }}</strong><span>发布</span></div>
            </div>

            <!-- Plan steps -->
            <ol v-if="planSteps.length" class="compact-plan">
              <li v-for="(step, index) in planSteps" :key="index">
                <span class="step-check">{{ stepStatusChar(step, index) }}</span>
                <div>
                  <strong>{{ humanizeStep(step.title || step.tool || step.step || `步骤 ${index + 1}`) }}</strong>
                  <small>{{ phaseLabel(step.phase) }}</small>
                </div>
              </li>
            </ol>

            <!-- Query result -->
            <section v-if="queryResult?.executed" class="query-result">
              <div class="query-result-title">
                <strong>查询结果</strong>
                <span>{{ queryRows.length }} 行 · {{ queryChannelText }}</span>
              </div>
              <div class="query-table-wrap">
                <table>
                  <thead><tr><th v-for="col in queryColumns" :key="col">{{ col }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(row, ri) in queryRows" :key="ri">
                      <td v-for="(col, ci) in queryColumns" :key="ci">{{ queryCell(row, col, ci) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- Next actions -->
            <div v-if="nextActions.length" class="next-actions">
              <strong>建议下一步</strong>
              <button
                v-for="action in nextActions"
                :key="String(action)"
                type="button"
                :disabled="isStreaming"
                @click="handleSend(String(action))"
              >
                {{ String(action) }}
              </button>
            </div>

            <!-- Technical details -->
            <details v-if="hasTechnicalDetails" class="tech-details">
              <summary>技术详情</summary>
              <pre><code>{{ technicalDetails }}</code></pre>
            </details>
          </article>
        </template>
      </div>

      <!-- Composer -->
      <Composer
        v-if="activeTab === 'chat'"
        :disabled="isStreaming"
        :placeholder="messages.length === 0 ? '描述你想做什么，例如：从OSS数据源建全链路数仓...' : '继续对话...'"
        @send="handleSend"
      />
    </main>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onMounted, ref, computed } from 'vue'
import MessageBubble from '@/components/agent/MessageBubble.vue'
import Composer from '@/components/agent/Composer.vue'
import WelcomePanel from '@/components/agent/WelcomePanel.vue'
import { idempotencyKey } from '@/utils/request'
import {
  agentModeLabel,
  buildAgentChatRequest,
  reconcileActiveInteraction,
  type AgentInteraction,
  type ConversationMeta,
  type InteractionAnswer,
} from '@/components/agent/chatInteraction'
import { streamAgentRun, type RunEvent } from '@/components/agent/runStream'
import { countOnlineCapabilities } from '@/components/agent/capabilityStatus'

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
  interaction?: AgentInteraction
}

interface AgentPayload {
  message: string
  success: boolean
  data?: {
    task_id?: string
    workflow_type?: string
    execution_mode?: string
    plan?: { summary?: string; steps?: PlanStep[] }
    steps?: PlanStep[]
    artifacts?: Array<Record<string, unknown>> | Record<string, unknown>
    query?: { columns?: string[]; rows?: unknown[][]; executed?: boolean; execution_channel?: string }
    publish_gate?: string
    publish_request?: Record<string, unknown>
    next_actions?: string[]
    agent_mode?: string
    interaction?: AgentInteraction | null
    conversation?: ConversationMeta
    [key: string]: unknown
  }
  error?: string | null
}

interface PlanStep {
  step_id?: string
  step?: string
  tool?: string
  title?: string
  phase?: string
  status?: string
}

const activeTab = ref<'chat' | 'cookie'>('chat')

const tabs = [
  { key: 'chat' as const, label: 'Agent 会话', icon: 'chat' },
  { key: 'cookie' as const, label: 'Cookie 管理', icon: 'chat' },
]

const messages = ref<ChatMessage[]>([])
const messagesContainer = ref<HTMLElement>()
const storedConversationId = typeof localStorage !== 'undefined' ? localStorage.getItem('conversation_id') : null
const conversationId = ref<string>(storedConversationId || idempotencyKey())
const activeInteractionId = ref<string | null>(null)
const conversationMeta = ref<ConversationMeta | null>(null)
if (typeof localStorage !== 'undefined' && !storedConversationId) {
  localStorage.setItem('conversation_id', conversationId.value)
}
const isStreaming = ref(false)
const isConnected = ref(false)
const mobileMenuOpen = ref(false)
const capabilitiesOnline = ref(0)
const totalCapabilities = ref(0)
const loadingCookie = ref(false)
const capabilityStatus = ref<Record<string, { label: string; status: string; online: boolean }>>({})
const lastPayload = ref<AgentPayload | null>(null)

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
  localStorage.setItem('conversation_id', conversationId.value)
  messages.value = []
  activeInteractionId.value = null
  conversationMeta.value = null
  lastPayload.value = null
  isStreaming.value = false
}

function sendQuickAction(text: string) {
  handleSend(text)
}

function handlePromptSelect(text: string) {
  handleSend(text)
}

// ---- Chat flow ----
async function handleSend(text: string) {
  if (!text.trim() || isStreaming.value) return

  messages.value.push({
    id: idempotencyKey(),
    role: 'user',
    content: text,
  })

  await nextTick(scrollToBottom)

  const assistantMsgId = idempotencyKey()
  messages.value.push({
    id: assistantMsgId,
    role: 'assistant',
    content: '',
    streaming: true,
  })

  isStreaming.value = true
  await runAgentTurn(text, assistantMsgId)
}

function applyRunEvent(event: RunEvent, assistantMsgId: string) {
  if (event.type === 'run.started') isConnected.value = true
  const index = messages.value.findIndex(message => message.id === assistantMsgId)
  if (index < 0) return
  if (event.type === 'decision.started') {
    messages.value[index].content = '正在理解本轮目标…'
  } else if (event.type === 'tool.started') {
    messages.value[index].content = `正在调用 ${humanizeStep(String(event.data.tool || '工具'))}…`
  } else if (event.type === 'tool.completed') {
    messages.value[index].content = event.data.success
      ? '工具已返回，正在整理结果…'
      : '工具返回了可处理的问题，正在生成恢复建议…'
  } else if (event.type === 'state.persisted') {
    messages.value[index].content = '会话状态已保存，正在生成回复…'
  }
}

async function runAgentTurn(
  text: string,
  assistantMsgId: string,
  interactionAnswer?: InteractionAnswer,
) {
  try {
    const request = buildAgentChatRequest(
      text,
      'auto',
      true,
      false,
      conversationId.value,
      undefined,
      interactionAnswer,
    )
    const response = await streamAgentRun<AgentPayload>(
      request,
      event => applyRunEvent(event, assistantMsgId),
    )
    applyAgentResponse(response, assistantMsgId)
  } catch (error) {
    if (interactionAnswer) await loadConversationHistory()
    const index = messages.value.findIndex(message => message.id === assistantMsgId)
    const failureMessage: ChatMessage = {
      id: assistantMsgId,
      role: 'assistant',
      content: `Agent 请求失败${interactionAnswer ? '，已重新同步会话状态' : ''}： ${error instanceof Error ? error.message : String(error)}`,
      streaming: false,
    }
    if (index >= 0) messages.value[index] = failureMessage
    else messages.value.push(failureMessage)
  } finally {
    isStreaming.value = false
    nextTick(scrollToBottom)
  }
}

function applyAgentResponse(response: AgentPayload, assistantMsgId?: string) {
  const interaction = response.data?.interaction ?? null
  const assistantMessage: ChatMessage = {
    id: assistantMsgId || idempotencyKey(),
    role: 'assistant',
    content: response.message,
    streaming: false,
    interaction: interaction ?? undefined,
    optionChips: response.data?.option_chips as ChatMessage['optionChips'],
  }
  const index = assistantMsgId
    ? messages.value.findIndex(message => message.id === assistantMsgId)
    : -1
  if (index >= 0) messages.value[index] = assistantMessage
  else messages.value.push(assistantMessage)

  messages.value = reconcileActiveInteraction(messages.value, interaction)
  activeInteractionId.value = interaction?.status === 'pending'
    ? interaction.interaction_id
    : null
  if (response.data?.conversation) conversationMeta.value = response.data.conversation
  lastPayload.value = response
}

async function handleInteractionAnswer(payload: { message: string; answer: InteractionAnswer }) {
  if (isStreaming.value) return
  const source = messages.value.find(
    message => message.interaction?.interaction_id === payload.answer.interaction_id,
  )
  if (source?.interaction) {
    source.interaction = { ...source.interaction, status: 'answered' }
  }
  activeInteractionId.value = null
  messages.value.push({ id: idempotencyKey(), role: 'user', content: payload.message })
  const assistantMsgId = idempotencyKey()
  messages.value.push({ id: assistantMsgId, role: 'assistant', content: '', streaming: true })
  isStreaming.value = true
  await nextTick(scrollToBottom)
  await runAgentTurn(payload.message, assistantMsgId, payload.answer)
}

async function loadConversationHistory() {
  try {
    const response = await fetch(
      `/agent/messages?conversation_id=${encodeURIComponent(conversationId.value)}`,
    )
    if (!response.ok) return
    const data = await response.json()
    const restored: ChatMessage[] = Array.isArray(data.messages)
      ? data.messages.map((message: Record<string, any>) => ({
          id: idempotencyKey(),
          role: message.role === 'user' ? 'user' : 'assistant',
          content: String(message.content ?? ''),
          interaction: message.payload?.interaction as AgentInteraction | undefined,
        }))
      : []
    const active = data.active_interaction as AgentInteraction | null
    messages.value = reconcileActiveInteraction(restored, active)
    conversationMeta.value = (data.conversation as ConversationMeta | undefined) ?? null
    activeInteractionId.value = active?.status === 'pending' ? active.interaction_id : null
    await nextTick(scrollToBottom)
  } catch {
    // A missing history endpoint must not block a new conversation.
  }
}

// ---- Cookie management ----
async function loadCapabilities() {
  try {
    const resp = await fetch('/agent/capabilities')
    const data = await resp.json()
    const caps = data.capabilities || {}
    totalCapabilities.value = Object.keys(caps).length
    capabilitiesOnline.value = countOnlineCapabilities(caps)
    capabilityStatus.value = formatCapabilityStatus(caps)
  } catch {
    // Keep existing values
  }
}

async function refreshCookieStatus() {
  loadingCookie.value = true
  try {
    await loadCapabilities()
  } finally {
    loadingCookie.value = false
  }
}

function formatCapabilityStatus(caps: Record<string, unknown>): Record<string, { label: string; status: string; online: boolean }> {
  const mapping: Record<string, { label: string; fallback: string }> = {
    agent_runtime: { label: 'Agent Runtime', fallback: '不可用' },
    ak_sk: { label: 'AK/SK', fallback: '未配置' },
    openapi: { label: 'OpenAPI', fallback: '未连接' },
    maxcompute: { label: 'MaxCompute', fallback: '未连接' },
    node_adapter: { label: '节点适配器', fallback: '不可用' },
    cookie_bff: { label: 'Cookie BFF', fallback: '未连接' },
    cdp_9222: { label: 'CDP 9222', fallback: '未连接' },
    official_mcp: { label: '官方 MCP', fallback: '未启用' },
    table_search: { label: '中文搜表', fallback: '不可用' },
    ida_query: { label: 'IDA 问数', fallback: '不可用' },
    llm: { label: 'LLM', fallback: '不可用' },
  }
  const result: Record<string, { label: string; status: string; online: boolean }> = {}
  for (const [key, { label, fallback }] of Object.entries(mapping)) {
    const val = caps[key] as Record<string, unknown> | boolean | string
    const online = val === true || val === 'true' || (typeof val === 'object' && val?.online === true)
    const observedStatus = typeof val === 'object' && val && typeof val.status === 'string'
      ? val.status
      : ''
    result[key] = {
      label,
      status: observedStatus || (online ? '就绪' : fallback),
      online,
    }
  }
  return result
}

// ---- Result card helpers ----
const planSteps = computed(() => {
  const d = lastPayload.value?.data
  return d?.plan?.steps ?? d?.steps ?? []
})

const agentMode = computed(() => {
  const d = lastPayload.value?.data
  return d?.agent_mode ?? (lastPayload.value?.success ? 'executed' : 'idle')
})

const modeText = computed(() => agentModeLabel(agentMode.value))

const resultTitle = computed(() => {
  const d = lastPayload.value?.data
  return d?.plan?.summary || lastPayload.value?.message || 'Agent 执行结果'
})

const stepMetricValue = computed(() => {
  const steps = planSteps.value
  if (!steps.length) return '—'
  const completed = steps.filter((s: PlanStep) => s.status === 'completed').length
  return `${completed}/${steps.length}`
})

const artifactCount = computed(() => {
  const d = lastPayload.value?.data
  const artifacts = d?.artifacts
  if (!artifacts) return 0
  if (Array.isArray(artifacts)) return artifacts.length
  return Object.keys(artifacts).length
})

const tableCount = computed(() => {
  const d = lastPayload.value?.data
  const devTables = d?.dev_tables
  if (!devTables) return 0
  if (typeof devTables === 'object' && !Array.isArray(devTables)) return Object.keys(devTables).length
  return 0
})

const publishGateText = computed(() => {
  const d = lastPayload.value?.data
  const pr = d?.publish_request
  if (pr?.deployment_status === 'deployed') return '已发布'
  if (pr?.deployment_status === 'failed') return '发布失败'
  if (pr?.status === 'rejected') return '已拒绝'
  if (pr) return '待审批'
  return '未发布'
})

const queryResult = computed(() => lastPayload.value?.data?.query)
const queryColumns = computed(() => queryResult.value?.columns ?? [])
const queryRows = computed(() => queryResult.value?.rows ?? [])
const queryChannelText = computed(() => queryResult.value?.execution_channel === 'cookie_bff' ? 'Cookie BFF 兜底' : 'MaxCompute AK/SK')

const nextActions = computed(() => lastPayload.value?.data?.next_actions ?? [])

const hasTechnicalDetails = computed(() => {
  const d = lastPayload.value?.data
  return d?.workflow_type || d?.execution_mode || d?.task_id || d?.capabilities
})

const technicalDetails = computed(() => {
  const d = lastPayload.value?.data
  if (!d) return ''
  return JSON.stringify({
    workflow_type: d.workflow_type,
    execution_mode: d.execution_mode,
    task_id: d.task_id,
  }, null, 2)
})

function stepStatusChar(step: PlanStep, index: number): string {
  const status = step.status ?? 'planned'
  if (status === 'completed') return '✓'
  if (status === 'failed' || status === 'error') return '✗'
  return `${index + 1}`
}

function phaseLabel(phase?: string): string {
  const map: Record<string, string> = {
    understand: '理解目标',
    inspect: '检查环境',
    plan: '生成计划',
    design: '设计模型',
    orchestrate: '编排任务',
    guardrail: '安全检查',
    execute: '开发执行',
  }
  return map[phase ?? ''] ?? ''
}

function humanizeStep(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function queryCell(row: unknown[], column: string, columnIndex: number): string {
  const value = Array.isArray(row) ? row[columnIndex] : (row as Record<string, unknown>)[column]
  return value === null || value === undefined ? '—' : String(value)
}

onMounted(async () => {
  await loadConversationHistory()
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
.sidebar.collapsed { display: none; }

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
  border-color: var(--color-accent-blue);
  color: var(--color-accent-blue);
  background: var(--gradient-subtle);
}
.new-chat-btn svg { width: 16px; height: 16px; }

.sidebar-section { margin-top: 20px; }
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

.sidebar-footer { margin-top: auto; padding-top: 16px; }
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
  background: var(--color-accent-green);
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.15);
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
.mobile-menu-btn svg { width: 20px; height: 20px; }

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

.header-tabs { display: flex; gap: 4px; }
.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.tab-btn:hover { background: var(--color-bg-tertiary); color: var(--color-text-primary); }
.tab-btn.active {
  background: var(--gradient-subtle);
  color: var(--color-accent-blue);
  font-weight: 600;
}
.tab-icon { width: 16px; height: 16px; }

.header-actions { display: flex; align-items: center; gap: 10px; }

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
  background: var(--color-accent-orange);
}
.conn-status.online .conn-dot { background: var(--color-accent-green); }

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
.refresh-btn:hover { background: var(--color-bg-tertiary); color: var(--color-text-secondary); }
.refresh-btn svg { width: 16px; height: 16px; }

/* Messages */
.messages-container { min-height: 0; overflow-y: auto; scrollbar-width: thin; }
.messages-list { padding: 24px; }

/* Cookie view */
.cookie-view {
  padding: 32px 24px;
  max-width: 800px;
  margin: 0 auto;
}
.cookie-header { margin-bottom: 24px; }
.cookie-header h2 {
  margin: 0 0 8px;
  font-size: 20px;
  font-weight: 700;
  color: var(--color-text-primary);
}
.cookie-header p {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-tertiary);
}
.cookie-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  margin-bottom: 20px;
}
.cap-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  background: var(--color-bg-secondary);
  transition: all 0.15s;
}
.cap-card.online {
  border-color: rgba(52, 211, 153, 0.3);
  background: rgba(52, 211, 153, 0.05);
}
.cap-icon {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-bg-tertiary);
  color: var(--color-text-tertiary);
  font-size: 14px;
  font-weight: 700;
  flex-shrink: 0;
}
.cap-card.online .cap-icon {
  background: rgba(52, 211, 153, 0.15);
  color: var(--color-accent-green);
}
.cap-info strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.cap-info span {
  font-size: 11px;
  color: var(--color-text-tertiary);
}
.refresh-cookie-btn {
  padding: 8px 20px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.refresh-cookie-btn:hover:not(:disabled) {
  border-color: var(--color-accent-blue);
  color: var(--color-accent-blue);
}
.refresh-cookie-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Result card */
.result-card {
  margin: 16px 24px 24px;
  overflow: hidden;
  border: 1px solid var(--color-border-primary);
  border-radius: var(--radius-lg);
  background: var(--color-bg-secondary);
}
.result-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--color-border-secondary);
}
.result-kicker {
  color: var(--color-text-tertiary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.12em;
}
.result-card h3 {
  max-width: 600px;
  margin: 4px 0 0;
  color: var(--color-text-primary);
  font-size: 13px;
  line-height: 1.5;
}
.result-state {
  height: fit-content;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  background: rgba(52, 211, 153, 0.15);
  color: var(--color-accent-green);
  font-size: 11px;
  font-weight: 700;
}
.result-state.blocked {
  background: rgba(248, 113, 113, 0.15);
  color: var(--color-accent-red);
}
.result-state.approval_required, .result-state.needs_context {
  background: rgba(251, 191, 36, 0.15);
  color: var(--color-accent-orange);
}

.result-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  border-bottom: 1px solid var(--color-border-secondary);
}
.result-metrics div {
  padding: 12px 16px;
  border-right: 1px solid var(--color-border-secondary);
}
.result-metrics div:last-child { border-right: 0; }
.result-metrics strong, .result-metrics span { display: block; }
.result-metrics strong {
  color: var(--color-text-primary);
  font-size: 18px;
}
.result-metrics span {
  margin-top: 4px;
  color: var(--color-text-tertiary);
  font-size: 11px;
}

.compact-plan {
  margin: 0;
  padding: 16px 20px;
  list-style: none;
}
.compact-plan li {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 36px;
}
.step-check {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--gradient-subtle);
  color: var(--color-accent-blue);
  font-size: 11px;
  font-weight: 800;
}

.query-result {
  margin: 0 16px 16px;
  overflow: hidden;
  border: 1px solid var(--color-border-primary);
  border-radius: var(--radius-md);
  background: var(--color-bg-tertiary);
}
.query-result-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--gradient-subtle);
  color: var(--color-text-secondary);
  font-size: 11px;
}
.query-result-title strong {
  color: var(--color-accent-blue);
  font-size: 12px;
}
.query-table-wrap { max-height: 280px; overflow: auto; }
.query-result table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  white-space: nowrap;
}
.query-result th, .query-result td {
  padding: 8px 12px;
  border-bottom: 1px solid var(--color-border-secondary);
  text-align: left;
}
.query-result th {
  position: sticky;
  top: 0;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  font-weight: 600;
}
.query-result td { color: var(--color-text-primary); }

.next-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 16px 20px;
}
.next-actions strong {
  display: block;
  margin-bottom: 6px;
  font-size: 11px;
}
.next-actions button {
  padding: 6px 12px;
  border: 1px solid var(--color-border-primary);
  border-radius: var(--radius-sm);
  background: var(--color-bg-tertiary);
  color: var(--color-accent-blue);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.next-actions button:hover:not(:disabled) {
  border-color: var(--color-border-active);
  background: var(--gradient-subtle);
}
.next-actions button:disabled {
  background: var(--color-bg-secondary);
  color: var(--color-text-tertiary);
  cursor: not-allowed;
}

.tech-details { padding: 0 20px 16px; }
.tech-details summary {
  font-size: 11px;
  color: var(--color-text-tertiary);
  cursor: pointer;
}
.tech-details pre {
  margin: 8px 0 0;
  max-height: 220px;
  overflow: auto;
  padding: 12px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  font-size: 11px;
  white-space: pre-wrap;
  font-family: var(--font-family-mono);
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
  .sidebar.collapsed { transform: translateX(-100%); }
  .mobile-menu-btn { display: grid; }
  .messages-list { padding: 16px; }
  .chat-header { padding: 0 16px; }
  .result-metrics { grid-template-columns: repeat(2, 1fr); }
}
</style>
