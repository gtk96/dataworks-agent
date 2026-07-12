<template>
  <div class="agent-workspace">
    <aside class="conversation-rail">
      <button class="new-chat" type="button" @click="resetConversation">
        <el-icon><Plus /></el-icon>
        新建会话
      </button>

      <div class="rail-section">
        <span class="rail-label">快捷能力</span>
        <button v-for="item in capabilityPrompts" :key="item.title" type="button" class="rail-item" @click="selectPrompt(item.text)">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.title }}</span>
        </button>
      </div>

      <div class="rail-bottom">
        <div class="runtime-card">
          <div class="runtime-title">
            <span class="status-dot" :class="{ online: healthyCapabilityCount > 0 }" />
            执行底座
          </div>
          <div class="runtime-grid">
            <span v-for="item in capabilityBadges" :key="item.label" :class="{ online: item.online }">
              {{ item.label }}
            </span>
          </div>
          <small>{{ healthyCapabilityCount }}/{{ capabilityBadges.length }} 项在线</small>
        </div>
      </div>
    </aside>

    <section class="conversation-main">
      <header class="chat-header">
        <div>
          <div class="product-row">
            <span class="product-mark">D</span>
            <strong>DataWorks Agent</strong>
            <span class="edition">Workspace</span>
          </div>
          <p>一句话完成建模、诊断、问数和 Cookie 管理</p>
        </div>
        <div class="header-actions">
          <span class="connection-pill">
            <i :class="{ online: isRealtime }" />{{ connectionText }}
          </span>
          <el-button text circle title="刷新能力状态" @click="loadCapabilities"><el-icon><Refresh /></el-icon></el-button>
        </div>
      </header>

      <div ref="messagesRef" class="message-stage" :class="{ empty: messages.length <= 1 }">
        <div v-if="messages.length <= 1" class="welcome-panel">
          <div class="agent-orb"><MagicStick /></div>
          <h1>今天想让数据 Agent 完成什么？</h1>
          <p>直接描述业务目标。无需选择工具，Agent 会自动组合 AK/SK、9222 Cookie 和阿里云官方 MCP。</p>
          <div class="prompt-grid">
            <button v-for="prompt in starterPrompts" :key="prompt.title" type="button" @click="selectPrompt(prompt.text)">
              <span class="prompt-icon"><el-icon><component :is="prompt.icon" /></el-icon></span>
              <strong>{{ prompt.title }}</strong>
              <small>{{ prompt.description }}</small>
              <el-icon class="prompt-arrow"><ArrowRight /></el-icon>
            </button>
          </div>
        </div>

        <div v-else class="message-list">
          <ChatMessage v-for="msg in messages" :key="msg.id" :message="msg" />
          <div v-if="loading" class="thinking-row">
            <span class="thinking-mark">D</span>
            <div><i /><i /><i /><em>正在理解目标并编排执行路径</em></div>
          </div>

          <article v-if="lastPayload" class="result-card">
            <header>
              <div>
                <span class="result-kicker">EXECUTION SUMMARY</span>
                <h3>{{ resultTitle }}</h3>
              </div>
              <span class="result-state" :class="agentMode">{{ modeText }}</span>
            </header>

            <div class="result-metrics">
              <div><strong>{{ stepMetricValue }}</strong><span>{{ stepMetricLabel }}</span></div>
              <div><strong>{{ artifactCards.length }}</strong><span>产物</span></div>
              <div><strong>{{ executionTables.length }}</strong><span>表 / 节点</span></div>
              <div><strong>{{ publishGateText }}</strong><span>发布状态</span></div>
            </div>

            <ol v-if="planSteps.length" class="compact-plan">
              <li v-for="(step, index) in planSteps" :key="step.step_id || step.step || step.tool || index">
                <span class="step-check" :class="`step-${String(step.status || 'planned').toLowerCase()}`">{{ stepStatus(step, index) }}</span>
                <div><strong>{{ humanizeStep(step.title || step.tool || step.step || `步骤 ${index + 1}`) }}</strong><small>{{ phaseLabel(step.phase) }}</small></div>
              </li>
            </ol>

            <div v-if="executionTables.length" class="created-resources">
              <span v-for="resource in executionTables" :key="resource">{{ resource }}</span>
            </div>

            <div v-if="responseErrors.length" class="response-errors">
              <strong>执行受阻</strong>
              <p v-for="error in responseErrors" :key="error">{{ error }}</p>
            </div>

            <div v-if="nextActions.length" class="next-actions">
              <strong>建议下一步</strong>
              <button v-for="action in nextActions" :key="action" type="button" @click="selectPrompt(action)">{{ action }}</button>
            </div>

            <el-collapse v-if="artifactCards.length || technicalDetails" class="technical-collapse">
              <el-collapse-item title="查看技术详情" name="details">
                <div v-if="artifactCards.length" class="artifact-list">
                  <article v-for="artifact in artifactCards" :key="artifact.label + artifact.value.slice(0, 20)">
                    <strong>{{ artifact.label }}</strong>
                    <pre v-if="artifact.isCode"><code>{{ artifact.value }}</code></pre>
                    <p v-else>{{ artifact.value }}</p>
                  </article>
                </div>
                <pre v-if="technicalDetails" class="json-detail"><code>{{ technicalDetails }}</code></pre>
              </el-collapse-item>
            </el-collapse>
          </article>

          <div v-if="clarifyingQuestions.length" class="question-card">
            <strong>还需要你确认</strong>
            <button v-for="question in clarifyingQuestions" :key="question" type="button" @click="appendQuestion(question)">
              {{ question }}<el-icon><ArrowRight /></el-icon>
            </button>
          </div>
        </div>
      </div>

      <footer class="composer-shell">
        <div class="composer-box" :class="{ focused: inputFocused }">
          <textarea
            ref="composerInput"
            v-model="input"
            rows="1"
            :disabled="loading"
            placeholder="给 DataWorks Agent 发消息，例如：把 orders 做成 ODS→DWD→DWS 小时链路并初始化"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
            @keydown.enter.exact.prevent="sendMessage"
          />
          <div class="composer-toolbar">
            <div class="mode-control">
              <span>执行模式</span>
              <el-segmented v-model="executionMode" :options="modeOptions" size="small" />
            </div>
            <span v-if="executionMode === 'dev_execute'" class="execution-warning">将写入开发环境</span>
            <el-popover placement="top-start" :width="320" trigger="click">
              <template #reference>
                <button class="settings-button" type="button" title="高级执行设置"><el-icon><Setting /></el-icon>高级设置</button>
              </template>
              <div class="run-settings">
                <strong>高级执行设置</strong>
                <label><span>初始化 ODS 数据</span><el-switch v-model="initializeData" /></label>
                <label><span>提交发布审批<small>只创建 Publish Gate，不自动上线</small></span><el-switch v-model="requestPublish" /></label>
              </div>
            </el-popover>
            <span class="guard-hint"><el-icon><Lock /></el-icon>生产变更受 Publish Gate 保护</span>
            <button class="send-button" type="button" :disabled="!input.trim() || loading" @click="sendMessage">
              <el-icon v-if="!loading"><Promotion /></el-icon><span v-else class="send-spinner" />
            </button>
          </div>
        </div>
        <p>Agent 可能会犯错，执行结果会保留审计记录；生产发布始终需要人工审批。</p>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import {
  ArrowRight,
  Connection,
  DataAnalysis,
  MagicStick,
  Plus,
  Promotion,
  Refresh,
  Search,
  Setting,
  Tools,
  Lock,
} from '@element-plus/icons-vue'
import ChatMessage from './ChatMessage.vue'
import { buildCapabilityBadges } from './capabilityStatus'
import { agentStepMarker, summarizeAgentSteps } from './stepStatus'
import { buildAgentChatRequest, requestAgentChat, type AgentExecutionMode } from './chatInteraction'

interface ChatMsg { id: string; text: string; isUser: boolean; timestamp: Date }
interface PlanStep { step_id?: string; step?: string; tool?: string; title?: string; phase?: string; status?: string }
interface ExecutionStatus { task_id: string; current_step: string | null; total_steps: number; completed_steps: number; failed_steps: number; steps: Record<string, { status: string }> }
interface AgentPayload {
  message: string
  success: boolean
  data?: {
    task_id?: string
    workflow_type?: string
    execution_mode?: string
    plan?: { summary?: string; steps?: PlanStep[] }
    steps?: PlanStep[]
    status?: ExecutionStatus | null
    artifacts?: Array<Record<string, unknown>> | Record<string, unknown>
    capabilities?: Record<string, unknown>
    executed?: Array<Record<string, unknown>>
    publish_gate?: string
    publish_request?: Record<string, unknown>
    clarifying_questions?: string[]
    next_actions?: string[]
    agent_mode?: string
    [key: string]: unknown
  }
  error?: string | null
}

const input = ref('')
const inputFocused = ref(false)
const loading = ref(false)
const executionMode = ref<AgentExecutionMode>('plan')
const initializeData = ref(true)
const requestPublish = ref(false)
const messages = ref<ChatMsg[]>([])
const messagesRef = ref<HTMLElement>()
const composerInput = ref<HTMLTextAreaElement>()
const ws = ref<WebSocket | null>(null)
const currentStatus = ref<ExecutionStatus | null>(null)
const lastPayload = ref<AgentPayload | null>(null)
const capabilities = ref<Record<string, unknown>>({})

const modeOptions = [
  { label: '规划', value: 'plan' },
  { label: '开发执行', value: 'dev_execute' },
]
const capabilityPrompts = [
  { title: '正向建模', icon: MagicStick, text: '把 <数据源> 的 <源表> 做成 ODS→DWD→DIM→DWS 全链路，创建开发表、节点和调度；先给我规划，不发布生产。' },
  { title: '逆向建模', icon: Search, text: '逆向分析存量表 <请输入真实表名或节点 ID>，读取真实结构、血缘、分层和语义候选。' },
  { title: '异常排查', icon: Tools, text: '排查 DataWorks 任务 <请输入任务 ID、实例 ID 或节点 ID>，检查日志、依赖和运行底座，给出恢复建议。' },
  { title: '自主问数', icon: DataAnalysis, text: '查询表 <请输入真实表名>：<请输入业务问题>。' },
  { title: 'Cookie 管理', icon: Connection, text: '检查 AK/SK、官方 MCP、Cookie BFF 和 9222 调试浏览器的当前状态。' },
]
const starterPrompts = [
  { title: '一句话建完整数仓链路', description: 'ODS、DWD、DIM、DWS 建表与任务一次完成', icon: MagicStick, text: capabilityPrompts[0].text },
  { title: '逆向理解存量模型', description: '读取结构、节点、血缘并生成语义候选', icon: Search, text: capabilityPrompts[1].text },
  { title: '排查失败与数据异常', description: '汇总日志、依赖和健康状态，给恢复方案', icon: Tools, text: capabilityPrompts[2].text },
  { title: '直接问业务数据', description: '只读 SQL 护栏下自然语言查询 MaxCompute', icon: DataAnalysis, text: capabilityPrompts[3].text },
]

const isRealtime = computed(() => ws.value?.readyState === WebSocket.OPEN)
const connectionText = computed(() => isRealtime.value ? '实时连接' : 'HTTP 可用')
const planSteps = computed(() => lastPayload.value?.data?.plan?.steps ?? lastPayload.value?.data?.steps ?? [])
const clarifyingQuestions = computed(() => lastPayload.value?.data?.clarifying_questions ?? [])
const nextActions = computed(() => lastPayload.value?.data?.next_actions ?? [])
const responseErrors = computed(() => {
  const errors = lastPayload.value?.data?.errors ?? []
  const primary = lastPayload.value?.error
  return [...new Set([...(Array.isArray(errors) ? errors.map(String) : []), ...(primary ? [primary] : [])])].slice(0, 3)
})
const agentMode = computed(() => lastPayload.value?.data?.agent_mode ?? (lastPayload.value?.success ? 'executed' : 'idle'))
const modeText = computed(() => ({ idle: '等待目标', proposal: '计划完成', needs_context: '待确认', approval_required: '等待审批', blocked: '执行受阻', executed: '开发完成' }[agentMode.value] ?? agentMode.value))
const resultTitle = computed(() => lastPayload.value?.data?.plan?.summary || lastPayload.value?.message || 'Agent 执行结果')
const stepSummary = computed(() => summarizeAgentSteps(planSteps.value))
const completedStepCount = computed(() => planSteps.value.length ? stepSummary.value.completed : (currentStatus.value?.completed_steps ?? 0))
const stepMetricValue = computed(() => planSteps.value.length ? `${completedStepCount.value}/${planSteps.value.length}` : '—')
const stepMetricLabel = computed(() => stepSummary.value.planned ? `已执行 · ${stepSummary.value.planned} 已规划` : '步骤完成')
const publishGateText = computed(() => lastPayload.value?.data?.publish_request ? '待审批' : lastPayload.value?.data?.publish_gate === 'approval_required' ? '待审批' : '未发布')
const executionTables = computed(() => {
  const rows = lastPayload.value?.data?.executed ?? []
  return rows.map((row) => String(row.table ?? row.node_name ?? '')).filter(Boolean)
})
const capabilityBadges = computed(() => buildCapabilityBadges(capabilities.value))
const healthyCapabilityCount = computed(() => capabilityBadges.value.filter((item) => item.online).length)
const artifactCards = computed(() => {
  const result: Array<{ label: string; value: string; isCode: boolean }> = []
  const artifacts = lastPayload.value?.data?.artifacts
  if (!artifacts) return result
  const append = (key: string, value: unknown) => {
    if (value === undefined || value === null || value === '') return
    const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
    result.push({ label: artifactLabel(key), value: text, isCode: key.includes('sql') || key.includes('ddl') || key.includes('content') })
  }
  if (Array.isArray(artifacts)) {
    artifacts.forEach((artifact) => append(String(artifact.type ?? artifact.name ?? 'artifact'), artifact.content ?? artifact.columns ?? artifact))
  } else {
    Object.entries(artifacts).forEach(([key, value]) => append(key, value))
  }
  return result.slice(0, 12)
})
const technicalDetails = computed(() => {
  const data = lastPayload.value?.data
  if (!data) return ''
  const detail = { workflow_type: data.workflow_type, execution_mode: data.execution_mode, task_id: data.task_id, capabilities: data.capabilities, publish_request: data.publish_request }
  return Object.values(detail).some(Boolean) ? JSON.stringify(detail, null, 2) : ''
})

onMounted(() => {
  resetConversation()
  connectWebSocket()
  loadCapabilities()
})
onUnmounted(() => ws.value?.close())

function resetConversation() {
  messages.value = [{ id: crypto.randomUUID(), text: '你好，我是 DataWorks Agent。你只需要说清业务目标，我会自动选择正向建模、逆向建模、异常排查、Cookie 管理或自主问数路径。', isUser: false, timestamp: new Date() }]
  lastPayload.value = null
  currentStatus.value = null
  input.value = ''
}
async function loadCapabilities() {
  try {
    const response = await fetch('/agent/capabilities')
    const payload = await response.json()
    capabilities.value = payload.capabilities ?? {}
  } catch { /* capability state stays degraded */ }
}
function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(`${protocol}//${window.location.host}/agent/ws`)
  ws.value = socket
  socket.onmessage = (event) => {
    const data = JSON.parse(event.data)
    if (data.type === 'response') handleAgentResponse(data.data)
    if (data.type === 'status') currentStatus.value = data.data
  }
  socket.onclose = () => { if (ws.value === socket) ws.value = null }
  socket.onerror = () => socket.close()
}
async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return
  input.value = ''
  messages.value.push({ id: crypto.randomUUID(), text, isUser: true, timestamp: new Date() })
  loading.value = true
  await nextTick(scrollToBottom)
  try {
    const payload = buildAgentChatRequest(text, executionMode.value, initializeData.value, requestPublish.value)
    handleAgentResponse(await requestAgentChat<AgentPayload>(payload))
  } catch (error) {
    handleAgentResponse({ message: `Agent 请求失败：${error instanceof Error ? error.message : String(error)}`, success: false })
  } finally {
    loading.value = false
  }
}
function handleAgentResponse(payload: AgentPayload) {
  lastPayload.value = payload
  if (payload.data?.capabilities) capabilities.value = payload.data.capabilities
  messages.value.push({ id: crypto.randomUUID(), text: payload.message, isUser: false, timestamp: new Date() })
  currentStatus.value = payload.data?.status ?? currentStatus.value
  loading.value = false
  nextTick(scrollToBottom)
}
function selectPrompt(text: string) { input.value = text; nextTick(() => composerInput.value?.focus()) }
function appendQuestion(question: string) { input.value = `${question}：`; nextTick(() => composerInput.value?.focus()) }
function scrollToBottom() { if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight }
function stepStatus(step: PlanStep, index: number) { return agentStepMarker(step, index) }
function phaseLabel(phase?: string) { return ({ understand: '理解目标', inspect: '检查环境', plan: '生成计划', design: '设计模型', orchestrate: '编排任务', guardrail: '安全检查', execute: '开发执行' }[phase ?? ''] ?? '执行步骤') }
function humanizeStep(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase()) }
function artifactLabel(key: string) { return ({ ddl: 'DDL', sql: 'DML / SQL', query_sql: '只读查询 SQL', node_sql: '节点 SQL', table_schema: '表结构', semantic_candidates: '语义候选' }[key] ?? key.replaceAll('_', ' ')) }
</script>

<style scoped>
.agent-workspace { height: calc(100vh - 66px); min-height: 680px; display: grid; grid-template-columns: 220px minmax(0, 1fr); overflow: hidden; background: #fff; border: 1px solid #e8e8eb; border-radius: 14px; box-shadow: 0 2px 12px rgba(0,0,0,.035); }
.conversation-rail { display: flex; flex-direction: column; padding: 14px 12px; border-right: 1px solid #ececef; background: #f8f8fa; }
.new-chat { height: 40px; display: flex; align-items: center; justify-content: center; gap: 8px; border: 1px solid #dedee3; border-radius: 9px; background: #fff; color: #202123; font-weight: 600; cursor: pointer; transition: .2s; }
.new-chat:hover { border-color: #6b4eff; color: #6b4eff; box-shadow: 0 4px 12px rgba(107,78,255,.1); }
.rail-section { margin-top: 24px; }
.rail-label { display: block; padding: 0 10px 8px; color: #9a9aa1; font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.rail-item { width: 100%; height: 40px; display: flex; align-items: center; gap: 10px; padding: 0 10px; border: 0; border-radius: 8px; background: transparent; color: #54545b; cursor: pointer; text-align: left; }
.rail-item:hover { color: #202123; background: #ededf1; }
.rail-item .el-icon { color: #777780; font-size: 16px; }
.rail-bottom { margin-top: auto; }
.runtime-card { padding: 12px; border: 1px solid #e2e2e6; border-radius: 10px; background: #fff; }
.runtime-title { display: flex; align-items: center; gap: 7px; color: #34343a; font-size: 12px; font-weight: 700; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #c5c5ca; }.status-dot.online { background: #20b26b; box-shadow: 0 0 0 3px rgba(32,178,107,.12); }
.runtime-grid { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0 8px; }.runtime-grid span { padding: 3px 6px; border-radius: 5px; background: #f0f0f2; color: #a2a2a8; font-size: 10px; }.runtime-grid span.online { background: #eaf8f1; color: #168552; }.runtime-card small { color: #9999a0; font-size: 10px; }
.conversation-main { min-width: 0; display: grid; grid-template-rows: 66px minmax(0,1fr) auto; background: #fff; }
.chat-header { display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #ededf0; }
.product-row { display: flex; align-items: center; gap: 9px; color: #202123; }.product-mark,.thinking-mark { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; background: linear-gradient(145deg,#7658ff,#5c3ef2); color: #fff; font-weight: 800; }.edition { padding: 3px 7px; border-radius: 5px; background: #f0edff; color: #6748ef; font-size: 10px; font-weight: 700; }.chat-header p { margin: 3px 0 0 37px; color: #9a9aa1; font-size: 11px; }
.header-actions { display: flex; align-items: center; gap: 5px; }.connection-pill { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border: 1px solid #e4e4e8; border-radius: 999px; color: #707078; font-size: 11px; }.connection-pill i { width: 6px; height: 6px; border-radius: 50%; background: #e6a23c; }.connection-pill i.online { background: #20b26b; }
.message-stage { overflow-y: auto; scrollbar-width: thin; }.message-stage.empty { display: grid; place-items: center; }
.welcome-panel { width: min(760px, calc(100% - 48px)); padding: 34px 0 50px; text-align: center; }.agent-orb { width: 54px; height: 54px; display: grid; place-items: center; margin: 0 auto 18px; border-radius: 17px; background: linear-gradient(145deg,#7658ff,#5034de); color: #fff; font-size: 24px; box-shadow: 0 12px 30px rgba(91,61,226,.22); }.welcome-panel h1 { margin: 0; color: #202123; font-size: 28px; letter-spacing: -.035em; }.welcome-panel>p { margin: 11px auto 28px; max-width: 600px; color: #85858c; font-size: 14px; line-height: 1.7; }
.prompt-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 10px; text-align: left; }.prompt-grid button { position: relative; min-height: 92px; display: grid; grid-template-columns: 34px 1fr 20px; grid-template-rows: auto auto; column-gap: 10px; align-items: center; padding: 15px; border: 1px solid #e4e4e8; border-radius: 11px; background: #fff; cursor: pointer; transition: .2s; }.prompt-grid button:hover { border-color: #b9abff; transform: translateY(-1px); box-shadow: 0 8px 22px rgba(49,38,102,.08); }.prompt-icon { grid-row: 1/3; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 9px; background: #f1eeff; color: #694af0; }.prompt-grid strong { color: #303036; font-size: 13px; }.prompt-grid small { color: #929299; font-size: 11px; line-height: 1.4; }.prompt-arrow { grid-column: 3; grid-row: 1/3; color: #b4b4ba; }
.message-list { width: min(900px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 36px; }.thinking-row { display: flex; gap: 12px; margin: 8px 0 22px; }.thinking-row>div { display: flex; align-items: center; gap: 4px; color: #888890; }.thinking-row i { width: 5px; height: 5px; border-radius: 50%; background: #7456f5; animation: pulse 1s infinite alternate; }.thinking-row i:nth-child(2){animation-delay:.2s}.thinking-row i:nth-child(3){animation-delay:.4s}.thinking-row em { margin-left: 6px; font-size: 12px; font-style: normal; }
.result-card { margin: 16px 0 24px 40px; overflow: hidden; border: 1px solid #e1e1e5; border-radius: 12px; background: #fff; }.result-card>header { display: flex; justify-content: space-between; gap: 18px; padding: 18px 20px; border-bottom: 1px solid #ededf0; }.result-kicker { color: #9a9aa1; font-size: 9px; font-weight: 800; letter-spacing: .12em; }.result-card h3 { max-width: 650px; margin: 5px 0 0; color: #29292f; font-size: 14px; line-height: 1.5; }.result-state { height: fit-content; padding: 5px 9px; border-radius: 6px; background: #ecf8f2; color: #168552; font-size: 11px; font-weight: 700; }.result-state.blocked { background: #fff0f0; color: #d14343; }.result-state.approval_required,.result-state.needs_context { background: #fff6e8; color: #b66a00; }
.result-metrics { display: grid; grid-template-columns: repeat(4,1fr); border-bottom: 1px solid #ededf0; }.result-metrics div { padding: 14px 18px; border-right: 1px solid #ededf0; }.result-metrics div:last-child { border-right: 0; }.result-metrics strong,.result-metrics span { display: block; }.result-metrics strong { color: #27272d; font-size: 16px; }.result-metrics span { margin-top: 3px; color: #9a9aa1; font-size: 10px; }
.compact-plan { margin: 0; padding: 16px 20px; list-style: none; }.compact-plan li { display: flex; align-items: center; gap: 10px; min-height: 38px; }.step-check { width: 22px; height: 22px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 50%; background: #eeebff; color: #6748ef; font-size: 10px; font-weight: 800; }.step-check.step-failed,.step-check.step-error,.step-check.step-blocked { background: #fff0f0; color: #d14343; } .step-check.step-warning { background: #fff6e8; color: #b66a00; } .step-check.step-skipped { background: #f0f0f2; color: #8b8b92; } .step-check.step-approval_required { background: #fff6e8; color: #b66a00; } .compact-plan strong,.compact-plan small { display: block; }.compact-plan strong { color: #4b4b52; font-size: 12px; }.compact-plan small { margin-top: 2px; color: #a2a2a8; font-size: 10px; }.created-resources { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 20px 16px; }.created-resources span { padding: 5px 8px; border: 1px solid #dedee3; border-radius: 6px; color: #5d5d65; font-family: ui-monospace,monospace; font-size: 10px; }
.technical-collapse { border-top: 1px solid #ededf0; border-bottom: 0; padding: 0 20px; }.technical-collapse :deep(.el-collapse-item__header){font-size:11px;color:#777780}.artifact-list article { margin-bottom: 10px; }.artifact-list strong { color: #55555d; font-size: 11px; }.artifact-list pre,.json-detail { max-height: 260px; overflow: auto; padding: 12px; border-radius: 8px; background: #17171b; color: #dddde3; font-size: 10px; white-space: pre-wrap; }.artifact-list p { color: #66666e; font-size: 12px; white-space: pre-wrap; }
.question-card { margin: 14px 0 20px 40px; padding: 16px; border: 1px solid #f0d5a8; border-radius: 10px; background: #fffaf2; }.question-card>strong { display: block; margin-bottom: 8px; color: #8d5b0e; font-size: 12px; }.question-card button { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border: 0; border-top: 1px solid #f3e5cb; background: transparent; color: #765723; font-size: 12px; cursor: pointer; text-align: left; }
.composer-shell { padding: 12px 24px 14px; background: linear-gradient(180deg,rgba(255,255,255,.5),#fff 18%); }.composer-box { width: min(900px,100%); margin: 0 auto; overflow: hidden; border: 1px solid #d9d9de; border-radius: 12px; background: #fff; box-shadow: 0 5px 18px rgba(0,0,0,.055); transition: .2s; }.composer-box.focused { border-color: #8a72f8; box-shadow: 0 0 0 3px rgba(107,78,255,.09),0 8px 24px rgba(0,0,0,.06); }.composer-box textarea { width: 100%; min-height: 52px; max-height: 140px; box-sizing: border-box; resize: none; padding: 15px 16px 8px; border: 0; outline: 0; color: #2c2c32; font: 13px/1.6 inherit; }.composer-box textarea::placeholder { color: #aaaab0; }.composer-toolbar { display: flex; align-items: center; gap: 10px; padding: 5px 7px 7px 11px; }.settings-button { display: flex; align-items: center; gap: 6px; padding: 5px 7px; border: 0; border-radius: 6px; background: transparent; color: #777780; font-size: 11px; cursor: pointer; }.settings-button:hover { background: #f2f2f4; }.guard-hint { display: flex; align-items: center; gap: 4px; color: #aaaab0; font-size: 10px; }.send-button { width: 31px; height: 31px; display: grid; place-items: center; margin-left: auto; border: 0; border-radius: 8px; background: #6748ef; color: #fff; cursor: pointer; }.send-button:disabled { background: #d8d4e8; cursor: not-allowed; }.send-spinner { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.45); border-top-color:#fff; border-radius:50%; animation:spin .8s linear infinite; }.composer-shell>p { margin: 7px 0 0; color: #aaaab0; font-size: 9px; text-align: center; }.run-settings>strong { display: block; margin-bottom: 10px; }.run-settings label { min-height: 44px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid #ededf0; color: #55555d; font-size: 12px; }.run-settings label span small { display: block; margin-top: 2px; color: #aaaab0; font-size: 9px; }
@keyframes pulse{to{opacity:.25;transform:translateY(-2px)}}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.agent-workspace{grid-template-columns:1fr}.conversation-rail{display:none}.result-metrics{grid-template-columns:repeat(2,1fr)}.result-metrics div:nth-child(2){border-right:0}.prompt-grid{grid-template-columns:1fr}.chat-header{padding:0 16px}.composer-shell{padding-left:12px;padding-right:12px}.message-list{width:calc(100% - 24px)}.welcome-panel{width:calc(100% - 24px)}}
.mode-control { display: flex; align-items: center; gap: 8px; color: #55555d; font-size: 11px; font-weight: 600; }
.execution-warning { padding: 4px 7px; border: 1px solid #ffd7a8; border-radius: 6px; background: #fff7e8; color: #a85b00; font-size: 10px; }
.response-errors { margin-top: 12px; padding: 11px 12px; border: 1px solid #ffd2d2; border-radius: 9px; background: #fff7f7; color: #8f2f2f; }
.response-errors strong, .next-actions strong { display: block; margin-bottom: 6px; font-size: 12px; }
.response-errors p { margin: 3px 0; font-size: 11px; line-height: 1.5; word-break: break-word; }
.next-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 12px; }
.next-actions strong { width: 100%; color: #55555d; }
.next-actions button { padding: 6px 9px; border: 1px solid #dedee6; border-radius: 7px; background: #fff; color: #5c45c7; font-size: 11px; cursor: pointer; }
.next-actions button:hover { border-color: #8a72f8; background: #f8f6ff; }
</style>
