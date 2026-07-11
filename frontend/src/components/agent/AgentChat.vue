<template>
  <div class="agent-chat">
    <section class="agent-console">
      <div class="console-main">
        <div class="console-toolbar">
          <div>
            <p class="eyebrow">DataWorks Agent</p>
            <h2>告诉我目标，我来规划和推进</h2>
          </div>
          <el-tag :type="connectionType" effect="plain">{{ connectionText }}</el-tag>
        </div>

        <div class="prompt-strip">
          <button
            v-for="prompt in prompts"
            :key="prompt.text"
            type="button"
            class="prompt-chip"
            @click="runPrompt(prompt.text)"
          >
            <span>{{ prompt.title }}</span>
            <small>{{ prompt.text }}</small>
          </button>
        </div>

        <div class="chat-messages" ref="messagesRef">
          <ChatMessage v-for="msg in messages" :key="msg.id" :message="msg" />
          <div v-if="loading" class="typing-card">
            <span />
            <span />
            <span />
            <strong>Agent 正在理解目标、拆解计划并生成草稿...</strong>
          </div>
        </div>

        <div class="composer">
          <div class="execution-controls">
            <el-radio-group v-model="executionMode" size="small">
              <el-radio-button value="dev_execute">开发执行</el-radio-button>
              <el-radio-button value="plan">规划预览</el-radio-button>
            </el-radio-group>
            <el-switch v-model="initializeData" active-text="初始化数据" />
            <el-checkbox v-model="requestPublish">完成后提交发布审批</el-checkbox>
          </div>
          <el-input
            v-model="input"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            resize="none"
            placeholder="例如：把 mysql 数据源 jky_singleshop 的 orders 表做成小时 ODS，再基于它建 dwd_trade_order_detail"
            :disabled="loading"
            @keydown.enter.exact.prevent="sendMessage"
          />
          <div class="composer-actions">
            <span>Enter 发送，Shift + Enter 换行。真实发布会进入 Publish Gate，不会越权执行。</span>
            <el-button type="primary" round size="large" :loading="loading" :disabled="!input.trim()" @click="sendMessage">
              交给 Agent
            </el-button>
          </div>
        </div>
      </div>

      <aside class="agent-panel">
        <div class="panel-section status-card">
          <div class="panel-title">
            <span>当前任务</span>
            <el-tag size="small" :type="modeTagType">
              {{ modeText }}
            </el-tag>
          </div>
          <TaskExecution
            v-if="currentStatus"
            :status="currentStatus"
            @retry="handleRetry"
            @cancel="handleCancel"
          />
          <el-empty v-else description="描述目标后，Agent 会在这里展示计划和进度。" :image-size="90" />
        </div>

        <div v-if="lastPayload?.data?.intent" class="panel-section">
          <div class="panel-title">理解结果</div>
          <dl class="insight-list">
            <div>
              <dt>意图</dt>
              <dd>{{ lastPayload.data.intent.action }}</dd>
            </div>
            <div v-if="lastPayload.data.intent.params?.table_name">
              <dt>目标表</dt>
              <dd>{{ lastPayload.data.intent.params.table_name }}</dd>
            </div>
            <div v-if="lastPayload.data.intent.params?.source_table">
              <dt>源表</dt>
              <dd>{{ lastPayload.data.intent.params.source_table }}</dd>
            </div>
            <div v-if="lastPayload.data.intent.params?.layer">
              <dt>分层</dt>
              <dd>{{ lastPayload.data.intent.params.layer }}</dd>
            </div>
            <div>
              <dt>置信度</dt>
              <dd>{{ Math.round((lastPayload.data.intent.confidence ?? 0) * 100) }}%</dd>
            </div>
          </dl>
        </div>

        <div v-if="planSteps.length" class="panel-section">
          <div class="panel-title">Agent 计划</div>
          <ol class="plan-list">
            <li v-for="step in planSteps" :key="step.step_id || step.step || step.tool">
              <strong>{{ step.title || step.tool || step.step }}</strong>
              <span>{{ phaseLabel(step.phase) }} / {{ riskLabel(step.risk) }}</span>
            </li>
          </ol>
        </div>

        <div v-if="artifactCards.length" class="panel-section">
          <div class="panel-title">产物草稿</div>
          <div class="artifact-list">
            <article v-for="artifact in artifactCards" :key="artifact.label" class="artifact-card">
              <strong>{{ artifact.label }}</strong>
              <pre v-if="artifact.isCode"><code>{{ artifact.value }}</code></pre>
              <p v-else>{{ artifact.value }}</p>
            </article>
          </div>
        </div>

        <div v-if="approvalItems.length" class="panel-section approval-section">
          <div class="panel-title">风险与审批</div>
          <ul class="next-list">
            <li v-for="item in approvalItems" :key="item">{{ item }}</li>
          </ul>
        </div>

        <div v-if="clarifyingQuestions.length" class="panel-section">
          <div class="panel-title">需要补充</div>
          <button
            v-for="question in clarifyingQuestions"
            :key="question"
            type="button"
            class="question-chip"
            @click="appendQuestion(question)"
          >
            {{ question }}
          </button>
        </div>

        <div v-if="nextActions.length" class="panel-section">
          <div class="panel-title">下一步建议</div>
          <ul class="next-list">
            <li v-for="action in nextActions" :key="action">{{ action }}</li>
          </ul>
        </div>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import ChatMessage from './ChatMessage.vue'
import TaskExecution from './TaskExecution.vue'

interface ChatMsg {
  id: string
  text: string
  isUser: boolean
  timestamp: Date
}

interface StepStatus {
  step_id: string
  tool: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  title?: string
  phase?: string
  error?: string | null
  warnings?: string[]
}

interface ExecutionStatus {
  task_id: string
  current_step: string | null
  total_steps: number
  completed_steps: number
  failed_steps: number
  steps: Record<string, StepStatus>
}

interface PlanStep {
  step_id?: string
  step?: string
  tool?: string
  title?: string
  phase?: string
  risk?: string
}

interface AgentPayload {
  message: string
  success: boolean
  data?: {
    task_id?: string
    intent?: {
      action: string
      confidence?: number
      params?: Record<string, string>
    }
    plan?: {
      summary?: string
      steps?: PlanStep[]
    }
    execution?: {
      step_results?: Array<{
        tool: string
        success: boolean
        data?: Record<string, unknown>
        warnings?: string[]
      }>
    }
    status?: ExecutionStatus | null
    artifacts?: Record<string, unknown> | Array<Record<string, unknown>>
    capabilities?: Record<string, unknown>
    executed?: Array<Record<string, unknown>>
    execution_mode?: string
    publish_request?: Record<string, unknown>
    approvals?: unknown[]
    clarifying_questions?: string[]
    next_actions?: string[]
    agent_mode?: string
  }
  error?: string | null
}

const input = ref('')
const loading = ref(false)
const executionMode = ref<'plan' | 'dev_execute'>('dev_execute')
const initializeData = ref(true)
const requestPublish = ref(false)
const messages = ref<ChatMsg[]>([])
const messagesRef = ref<HTMLElement>()
const ws = ref<WebSocket | null>(null)
const currentStatus = ref<ExecutionStatus | null>(null)
const lastPayload = ref<AgentPayload | null>(null)

const prompts = [
  { title: 'MySQL 到 ODS+DWD', text: '把 mysql 数据源 jky_singleshop 的 orders 表做成小时 ODS，再基于它建 dwd_trade_order_detail' },
  { title: '现有 ODS 建 DWD', text: '基于 ods_order 设计 dwd_trade_order_detail，生成 DDL、DML、依赖和发布前风险检查' },
  { title: '发布前检查', text: '对 dwd_trade_order_detail 做发布前检查，只给方案和风险，不要直接发布' },
]

const planSteps = computed(() => lastPayload.value?.data?.plan?.steps ?? [])
const nextActions = computed(() => lastPayload.value?.data?.next_actions ?? [])
const clarifyingQuestions = computed(() => lastPayload.value?.data?.clarifying_questions ?? [])
const connectionText = computed(() => (ws.value?.readyState === WebSocket.OPEN ? '实时连接' : 'HTTP 兜底'))
const connectionType = computed(() => (ws.value?.readyState === WebSocket.OPEN ? 'success' : 'warning'))
const agentMode = computed(() => lastPayload.value?.data?.agent_mode ?? (currentStatus.value ? 'proposal' : 'idle'))
const modeText = computed(() => {
  const map: Record<string, string> = {
    idle: '等待目标',
    proposal: '计划已生成',
    needs_context: '需要上下文',
    approval_required: '等待审批',
    blocked: '需要处理',
    executed: '开发已执行',
  }
  return map[agentMode.value] ?? agentMode.value
})
const modeTagType = computed(() => {
  if (agentMode.value === 'blocked') return 'danger'
  if (agentMode.value === 'approval_required' || agentMode.value === 'needs_context') return 'warning'
  if (agentMode.value === 'proposal' || agentMode.value === 'executed') return 'success'
  return 'info'
})

const artifactCards = computed(() => {
  const cards: Array<{ label: string; value: string; isCode: boolean }> = []
  const artifacts = lastPayload.value?.data?.artifacts ?? {}
  if (Array.isArray(artifacts)) {
    for (const artifact of artifacts) {
      const type = String(artifact.type ?? 'artifact')
      const value = artifact.content ?? artifact
      cards.push({
        label: `${artifactLabel(type)}${artifact.name ? ` · ${artifact.name}` : ''}`,
        value: stringifyArtifact(value),
        isCode: type.includes('ddl') || type.includes('sql'),
      })
    }
  } else {
    for (const [key, value] of Object.entries(artifacts)) {
      if (value === undefined || value === null || value === '') continue
      cards.push({ label: artifactLabel(key), value: stringifyArtifact(value), isCode: key === 'ddl' || key === 'sql' })
    }
  }
  const stepResults = lastPayload.value?.data?.execution?.step_results ?? []
  for (const result of stepResults) {
    const data = result.data ?? {}
    if (typeof data.ddl === 'string') cards.push({ label: 'MaxCompute DDL', value: data.ddl, isCode: true })
    if (typeof data.sql === 'string') cards.push({ label: 'SQL / DML', value: data.sql, isCode: true })
    if (typeof data.summary === 'string') cards.push({ label: String(data.artifact_type ?? result.tool), value: data.summary, isCode: false })
  }
  return cards.slice(0, 8)
})

const approvalItems = computed(() => {
  const items: string[] = []
  const approvals = lastPayload.value?.data?.approvals ?? []
  for (const approval of approvals) items.push(stringifyArtifact(approval))
  const stepResults = lastPayload.value?.data?.execution?.step_results ?? []
  for (const result of stepResults) {
    const data = result.data ?? {}
    if (data.requires_approval || data.publish_gate) {
      items.push(`${result.tool}: 真实写入或发布前必须经过 Publish Gate 审批`)
    }
  }
  return Array.from(new Set(items))
})

onMounted(() => {
  messages.value.push({
    id: 'welcome',
    text: '我是你的 DataWorks Agent。直接用一句话描述目标即可：正向/逆向建模、异常排查、Cookie 管理、自主问数，以及 ODS→DWD/DIM→DWS 全链路。默认可在开发环境建表、建 Saved 节点、配置调度并初始化；正式发布仍会停在 Publish Gate 等待审批。',
    isUser: false,
    timestamp: new Date(),
  })
  connectWebSocket()
})

onUnmounted(() => {
  ws.value?.close()
})

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(`${protocol}//${window.location.host}/agent/ws`)
  ws.value = socket

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'response') {
      handleAgentResponse(data.data)
    } else if (data.type === 'status') {
      currentStatus.value = data.data
      nextTick(scrollToBottom)
    }
  }

  socket.onclose = () => {
    if (ws.value === socket) ws.value = null
  }

  socket.onerror = () => {
    socket.close()
  }
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return

  input.value = ''
  messages.value.push({ id: crypto.randomUUID(), text, isUser: true, timestamp: new Date() })
  await nextTick(scrollToBottom)

  loading.value = true
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({
      message: text,
      execution_mode: executionMode.value,
      initialize_data: initializeData.value,
      publish: requestPublish.value,
    }))
    return
  }

  await sendViaHttp(text)
}

async function sendViaHttp(text: string) {
  try {
    const response = await fetch('/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text,
        execution_mode: executionMode.value,
        initialize_data: initializeData.value,
        publish: requestPublish.value,
      }),
    })
    const payload = await response.json()
    handleAgentResponse(payload)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    messages.value.push({
      id: crypto.randomUUID(),
      text: `Agent 连接失败：${message}`,
      isUser: false,
      timestamp: new Date(),
    })
    loading.value = false
    await nextTick(scrollToBottom)
  }
}

function handleAgentResponse(payload: AgentPayload) {
  lastPayload.value = payload
  messages.value.push({
    id: crypto.randomUUID(),
    text: payload.message,
    isUser: false,
    timestamp: new Date(),
  })
  currentStatus.value = payload.data?.status ?? currentStatus.value
  loading.value = false
  nextTick(scrollToBottom)
}

function runPrompt(prompt: string) {
  input.value = prompt
  sendMessage()
}

function appendQuestion(question: string) {
  input.value = input.value ? `${input.value}\n${question}：` : `${question}：`
}

function handleRetry() {
  input.value = '诊断上一次失败步骤，并给出安全恢复和重试方案'
  sendMessage()
}

function handleCancel() {
  loading.value = false
  messages.value.push({
    id: crypto.randomUUID(),
    text: '已停止本地等待。当前 Agent 路径默认是 dry-run/proposal，不会直接取消或修改线上 DataWorks 任务。',
    isUser: false,
    timestamp: new Date(),
  })
}

function scrollToBottom() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

function phaseLabel(phase?: string) {
  const map: Record<string, string> = {
    understand: '理解',
    inspect: '检查',
    plan: '规划',
    design: '设计',
    orchestrate: '编排',
    guardrail: '风控',
    draft: '产物',
    next: '建议',
    execute: '执行',
  }
  return phase ? map[phase] ?? phase : '执行'
}

function riskLabel(risk?: string) {
  const map: Record<string, string> = { low: '低风险', medium: '中风险', high: '高风险' }
  return risk ? map[risk] ?? risk : '低风险'
}

function artifactLabel(key: string) {
  const map: Record<string, string> = {
    ddl: 'DDL 草稿',
    sql: 'SQL / DML 草稿',
    schedule: '调度建议',
    lineage: '血缘影响',
    risk_report: '风险报告',
  }
  return map[key] ?? key
}

function stringifyArtifact(value: unknown) {
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}
</script>

<style scoped>
.agent-chat {
  min-height: 680px;
}

.agent-console {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 20px;
}

.console-main,
.agent-panel {
  border: 1px solid rgba(98, 128, 210, 0.14);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow: 0 24px 70px rgba(31, 45, 91, 0.1);
  backdrop-filter: blur(18px);
}

.console-main {
  display: flex;
  min-height: 720px;
  overflow: hidden;
  flex-direction: column;
}

.console-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 22px 24px 12px;
}

.eyebrow {
  margin: 0 0 6px;
  color: #2456d6;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.console-toolbar h2 {
  margin: 0;
  color: #18233f;
  font-size: 22px;
  letter-spacing: -0.02em;
}

.prompt-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
  padding: 0 24px 16px;
}

.prompt-chip {
  cursor: pointer;
  border: 1px solid rgba(64, 158, 255, 0.18);
  border-radius: 18px;
  padding: 12px 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f6f8ff 100%);
  color: #1f2a44;
  text-align: left;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.prompt-chip:hover {
  transform: translateY(-2px);
  border-color: rgba(64, 158, 255, 0.45);
  box-shadow: 0 10px 24px rgba(64, 158, 255, 0.12);
}

.prompt-chip span,
.prompt-chip small {
  display: block;
}

.prompt-chip span {
  font-weight: 700;
}

.prompt-chip small {
  margin-top: 5px;
  color: #667085;
  line-height: 1.45;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 18px 24px 8px;
  background: linear-gradient(180deg, rgba(246, 248, 255, 0.5), rgba(255, 255, 255, 0));
}

.typing-card {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  margin: 4px 0 16px 44px;
  padding: 12px 16px;
  border-radius: 16px;
  background: #f3f6ff;
  color: #52627a;
}

.typing-card span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #409eff;
  animation: pulse 1.2s infinite ease-in-out;
}

.typing-card span:nth-child(2) { animation-delay: 0.15s; }
.typing-card span:nth-child(3) { animation-delay: 0.3s; }

@keyframes pulse {
  0%, 80%, 100% { opacity: 0.35; transform: scale(0.75); }
  40% { opacity: 1; transform: scale(1); }
}

.execution-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  color: #52627a;
}

.composer {
  padding: 16px;
  border-top: 1px solid rgba(98, 128, 210, 0.12);
  background: rgba(255, 255, 255, 0.92);
}

.composer :deep(.el-textarea__inner) {
  border-radius: 18px;
  padding: 14px 16px;
  box-shadow: none;
}

.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  color: #98a2b3;
  font-size: 12px;
}

.agent-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  min-height: 720px;
}

.panel-section {
  border: 1px solid rgba(98, 128, 210, 0.12);
  border-radius: 22px;
  padding: 16px;
  background: linear-gradient(180deg, #ffffff 0%, #f7f9ff 100%);
}

.approval-section {
  border-color: rgba(245, 158, 11, 0.28);
  background: linear-gradient(180deg, #fffaf0 0%, #fff7ed 100%);
}

.panel-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
  color: #1f2a44;
  font-weight: 800;
}

.insight-list {
  display: grid;
  gap: 10px;
  margin: 0;
}

.insight-list div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.insight-list dt {
  color: #667085;
}

.insight-list dd {
  margin: 0;
  color: #1f2a44;
  font-weight: 700;
}

.plan-list,
.next-list {
  margin: 0;
  padding-left: 18px;
}

.plan-list li,
.next-list li {
  margin-bottom: 10px;
  color: #344054;
  line-height: 1.55;
}

.plan-list strong,
.plan-list span {
  display: block;
}

.plan-list span {
  color: #98a2b3;
  font-size: 12px;
  text-transform: uppercase;
}

.artifact-list {
  display: grid;
  gap: 10px;
}

.artifact-card {
  padding: 12px;
  border: 1px solid rgba(64, 158, 255, 0.14);
  border-radius: 16px;
  background: #fff;
}

.artifact-card strong {
  display: block;
  margin-bottom: 8px;
  color: #1f2a44;
}

.artifact-card p,
.artifact-card pre {
  margin: 0;
  color: #52627a;
  line-height: 1.6;
}

.artifact-card pre {
  max-height: 220px;
  overflow: auto;
  padding: 10px;
  border-radius: 12px;
  background: #111827;
  color: #e5e7eb;
  font-size: 12px;
}

.question-chip {
  display: block;
  width: 100%;
  cursor: pointer;
  border: 1px solid rgba(64, 158, 255, 0.18);
  border-radius: 14px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fff;
  color: #2456d6;
  text-align: left;
}

@media (max-width: 1280px) {
  .prompt-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 1180px) {
  .agent-console {
    grid-template-columns: 1fr;
  }

  .agent-panel {
    min-height: unset;
  }
}

@media (max-width: 760px) {
  .prompt-strip {
    grid-template-columns: 1fr;
  }

  .console-toolbar,
  .composer-actions {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
