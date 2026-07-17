<template>
  <div class="agent-workspace">
    <!-- Left rail: quick actions & status -->
    <aside class="conversation-rail">
      <button class="new-chat-btn" type="button" @click="resetConversation">
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
          <small>{{ healthyCapabilityCount }}/{{ capabilityBadges.length }} 通道就绪</small>
        </div>
      </div>
    </aside>

    <!-- Main chat area -->
    <section class="conversation-main">
      <header class="chat-header">
        <div>
          <div class="product-row">
            <strong>DataWorks Agent</strong>
            <span class="edition">Workspace</span>
          </div>
          <p>一句话完成数仓建模、诊断、问数和审批编排</p>
        </div>
        <div class="header-actions">
          <span class="connection-pill">
            <span class="conn-dot" :class="{ online: isRealtime }" />
            {{ connectionText }}
          </span>
          <el-button :icon="Refresh" circle text size="small" title="刷新能力状态" @click="loadCapabilities" />
        </div>
      </header>

      <div ref="messagesRef" class="message-stage" :class="{ empty: messages.length <= 1 }">
        <!-- Welcome panel (shown when no messages yet) -->
        <div v-if="messages.length <= 1" class="welcome-panel">
          <div class="agent-orb"><MagicStick /></div>
          <h1>今天想让数据 Agent 完成什么？</h1>
          <p>直接描述业务目标。Agent 负责自动编排执行路径，改节点、删节点和生产发布会停在确认点。</p>
          <div class="prompt-grid">
            <button v-for="prompt in starterPrompts" :key="prompt.title" type="button" @click="selectPrompt(prompt.text)">
              <span class="prompt-icon"><el-icon><component :is="prompt.icon" /></el-icon></span>
              <div>
                <strong>{{ prompt.title }}</strong>
                <small>{{ prompt.description }}</small>
              </div>
              <el-icon class="prompt-arrow"><ArrowRight /></el-icon>
            </button>
          </div>
        </div>

        <!-- Message list (shown when there are messages) -->
        <div v-else class="message-list">
          <ChatMessage v-for="msg in messages" :key="msg.id" :message="msg" />
          <div v-if="loading" class="thinking-row">
            <div class="thinking-dots">
              <span /><span /><span />
            </div>
            <em>正在理解目标并编排执行路径</em>
          </div>

          <!-- Result card -->
          <article v-if="lastPayload" class="result-card">
            <header class="result-header">
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

            <!-- Plan steps -->
            <ol v-if="planSteps.length" class="compact-plan">
              <li v-for="(step, index) in planSteps" :key="step.step_id || step.step || step.tool || index">
                <span class="step-check" :class="`step-${String(step.status || 'planned').toLowerCase()}`">{{ stepStatus(step, index) }}</span>
                <div>
                  <strong>{{ humanizeStep(step.title || step.tool || step.step || `步骤 ${index + 1}`) }}</strong>
                  <small>{{ phaseLabel(step.phase) }}</small>
                </div>
              </li>
            </ol>

            <!-- Source discovery -->
            <section v-if="sourceDiscovery.visible" class="source-discovery" :class="{ success: sourceDiscovery.success }" data-testid="source-discovery">
              <div class="source-discovery-title">
                <div><strong>OSS 字段探测</strong><span>优先复用 DataWorks 托管元数据，不展示或保存样本正文</span></div>
                <span>{{ sourceDiscovery.statusText }}</span>
              </div>
              <div class="source-discovery-grid">
                <div><small>探测通道</small><strong>{{ sourceDiscovery.channelText }}</strong></div>
                <div v-if="sourceDiscovery.datasourceName"><small>托管数据源</small><strong>{{ sourceDiscovery.datasourceName }}</strong></div>
                <div v-if="sourceDiscovery.metadataSourceText"><small>元数据来源</small><strong>{{ sourceDiscovery.metadataSourceText }}</strong></div>
                <div><small>Bucket</small><strong>{{ sourceDiscovery.bucket }}</strong></div>
                <div><small>Prefix</small><strong>{{ sourceDiscovery.prefix }}</strong></div>
                <div><small>文件格式</small><strong>{{ sourceDiscovery.fileFormat }}</strong></div>
                <div><small>字段数量</small><strong>{{ sourceDiscovery.columnCount }}</strong></div>
              </div>
              <div v-if="sourceDiscovery.success" class="source-discovery-evidence">
                <span v-if="sourceDiscovery.sampleObject">样本对象：{{ sourceDiscovery.sampleObject }}</span>
                <span>未展示或保存样本正文</span>
              </div>
              <div v-else class="source-discovery-blocker">
                <strong>{{ sourceDiscovery.errorCode || 'schema_discovery_failed' }}</strong>
                <p>{{ sourceDiscovery.error || '字段探测尚未完成。' }}</p>
                <p v-if="sourceDiscovery.nextAction"><b>下一步：</b>{{ sourceDiscovery.nextAction }}</p>
              </div>
            </section>

            <!-- Created resources -->
            <div v-if="executionTables.length" class="created-resources">
              <span v-for="resource in executionTables" :key="resource">{{ resource }}</span>
            </div>

            <!-- Publish approval -->
            <section v-if="publishRequest" class="publish-approval" data-testid="publish-approval">
              <div class="publish-approval-head">
                <div>
                  <small>PUBLISH GATE</small>
                  <strong>{{ publishRequestStatusText }}</strong>
                </div>
                <span>{{ String(publishRequest.table_name || '待发布节点') }}</span>
              </div>
              <p>开发表、节点与调度已保存为草稿。只有点击"批准并发布"后，Agent 才会调用 DataWorks 发布接口。</p>
              <div v-if="String(publishRequest.status || 'pending') === 'pending'" class="publish-actions">
                <button type="button" class="approve-button" :disabled="Boolean(reviewingDecision)" @click="reviewPublish('approve')">
                  {{ reviewingDecision === 'approve' ? '正在发布…' : '批准并发布' }}
                </button>
                <button type="button" class="reject-button" :disabled="Boolean(reviewingDecision)" @click="reviewPublish('reject')">
                  {{ reviewingDecision === 'reject' ? '正在拒绝…' : '拒绝' }}
                </button>
              </div>
              <p v-if="publishReviewFeedback" class="publish-feedback">{{ publishReviewFeedback }}</p>
            </section>

            <!-- Semantic proof -->
            <section v-if="semanticPlan" class="semantic-proof" data-testid="semantic-proof">
              <div class="semantic-proof-title">
                <div><strong>语义选表与闭环证据</strong><span>展示资产、字段、粒度、时效与对账证据</span></div>
                <span>{{ semanticMetricVersion }}</span>
              </div>
              <div class="semantic-proof-grid">
                <div><small>认证指标</small><strong>{{ semanticPlan.metric_name || semanticPlan.metric_id }}</strong></div>
                <div><small>官方表</small><strong>{{ semanticPlan.table || '—' }}</strong></div>
                <div><small>数据专辑</small><strong>{{ semanticAlbumText }}</strong></div>
                <div><small>DDL 核验</small><strong>{{ semanticValidationText }}</strong></div>
              </div>
              <div v-if="semanticAlbumStatusText" class="semantic-proof-row"><small>专辑关系</small><span>{{ semanticAlbumStatusText }}</span></div>
              <div v-if="semanticDimensionText" class="semantic-proof-row"><small>分析维度</small><span>{{ semanticDimensionText }}</span></div>
              <div v-if="semanticFilterText" class="semantic-proof-row"><small>固定口径</small><code>{{ semanticFilterText }}</code></div>
              <ul v-if="semanticEvidence.length"><li v-for="item in semanticEvidence" :key="item">{{ item }}</li></ul>
              <div v-if="semanticVerificationChecks.length" class="semantic-checks">
                <span v-for="check in semanticVerificationChecks" :key="check.name" :class="{ passed: check.passed }">
                  {{ check.passed ? '✓' : '×' }} {{ check.label }}
                </span>
              </div>
            </section>

            <!-- Query result -->
            <section v-if="queryResult?.executed" class="query-result" data-testid="query-result">
              <div class="query-result-title">
                <strong>真实查询结果</strong>
                <span>{{ queryRows.length }} 行 · {{ queryChannelText }}</span>
              </div>
              <div class="query-table-wrap">
                <table>
                  <thead><tr><th v-for="column in queryColumns" :key="column">{{ column }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in queryRows" :key="rowIndex">
                      <td v-for="(column, columnIndex) in queryColumns" :key="column">{{ queryCell(row, column, columnIndex) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>

            <!-- Errors -->
            <div v-if="responseErrors.length" class="response-errors">
              <strong>执行受阻</strong>
              <p v-for="error in responseErrors" :key="error">{{ error }}</p>
            </div>

            <!-- Next actions -->
            <div v-if="nextActions.length || customInputHint" class="next-actions">
              <strong>建议下一步</strong>
              <button
                v-for="action in nextActions"
                :key="nextActionKey(action)"
                type="button"
                :disabled="loading"
                @click="chooseNextAction(action)"
              >
                {{ nextActionLabel(action) }}
              </button>
              <small v-if="customInputHint" class="custom-input-hint">{{ customInputHint }}</small>
            </div>

            <!-- Technical details -->
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

          <!-- Clarifying questions -->
          <div v-if="clarifyingQuestions.length" class="question-card">
            <strong>还需要你确认</strong>
            <button v-for="question in clarifyingQuestions" :key="question" type="button" @click="prepareClarification(question)">
              {{ question }}<el-icon><ArrowRight /></el-icon>
            </button>
          </div>
        </div>
      </div>

      <!-- Composer (input area) -->
      <footer class="composer-shell">
        <div class="composer-box" :class="{ focused: inputFocused }">
          <textarea
            ref="composerInput"
            v-model="input"
            rows="1"
            :disabled="loading"
            :placeholder="composerPlaceholder"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
            @keydown.enter.exact.prevent="() => void sendMessage()"
          />
          <div class="composer-toolbar">
            <div class="mode-control">
              <el-segmented v-model="executionMode" :options="modeOptions" size="small" />
            </div>
            <span v-if="executionMode === 'dev_execute'" class="execution-warning">仅开发环境写入；改/删/发布会先停下确认</span>
            <span class="guard-hint"><el-icon><Lock /></el-icon>{{ modeDescription }}</span>
            <button class="send-button" type="button" :disabled="!input.trim() || loading" @click="() => void sendMessage()">
              <el-icon v-if="!loading"><Promotion /></el-icon>
              <span v-else class="send-spinner" />
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
  Tools,
  Lock,
} from '@element-plus/icons-vue'
import ChatMessage from './ChatMessage.vue'
import { buildCapabilityBadges } from './capabilityStatus'
import { agentStepMarker, summarizeAgentSteps } from './stepStatus'
import { buildSourceDiscoveryView } from './sourceDiscovery'
import { buildExecutionResources } from './executionResources'
import {
  buildAgentChatRequest,
  requestAgentChat,
  reviewPublishRequest,
  type AgentContextUpdates,
  type AgentExecutionMode,
  type AgentInteraction,
  type InteractionAnswer,
} from './chatInteraction'
import { idempotencyKey } from '@/utils/request'

interface ChatMsg {
  id: string
  text: string
  isUser: boolean
  timestamp: Date
  interaction?: AgentInteraction
}
interface PlanStep { step_id?: string; step?: string; tool?: string; title?: string; phase?: string; status?: string }
interface ExecutionStatus { task_id: string; current_step: string | null; total_steps: number; completed_steps: number; failed_steps: number; steps: Record<string, { status: string }> }
interface SemanticPlan {
  metric_id?: string
  metric_name?: string
  metric_version?: number
  table?: string
  albums?: Array<{ name?: string }>
  selected_dimensions?: string[]
  caliber?: { fixed_filters?: Record<string, unknown> }
  selection_evidence?: string[]
  metadata_validation?: { status?: string; channel?: string }
  album_validation?: { status?: string; certified_table_present?: boolean }
}
interface NextAction {
  id: string
  label: string
  value?: string
  payload?: AgentContextUpdates
  requires_custom_input?: boolean
}
type NextActionValue = string | NextAction

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
    next_actions?: NextActionValue[]
    allow_custom_input?: boolean
    custom_input_hint?: string
    agent_mode?: string
    interaction?: AgentInteraction
    semantic_plan?: SemanticPlan
    source_discovery?: Record<string, unknown>
    query?: {
      sql?: string
      columns?: string[]
      rows?: Array<unknown[] | Record<string, unknown>>
      row_count?: number
      executed?: boolean
      execution_channel?: string
    }
    [key: string]: unknown
  }
  error?: string | null
}

// Persist conversation_id in localStorage
const storedConvId = typeof localStorage !== 'undefined' ? localStorage.getItem('conversation_id') : null
const conversationId = ref(storedConvId || idempotencyKey())

if (typeof localStorage !== 'undefined' && !storedConvId) {
  localStorage.setItem('conversation_id', conversationId.value)
}

const input = ref('')
const reviewingDecision = ref<'' | 'approve' | 'reject'>('')
const publishReviewFeedback = ref('')
const inputFocused = ref(false)
const activeClarifyingQuestion = ref('')
const loading = ref(false)
const executionMode = ref<AgentExecutionMode>('auto')
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
  { label: '自动编排', value: 'auto' },
  { label: '只规划', value: 'plan' },
  { label: '开发执行(dev)', value: 'dev_execute' },
]
const capabilityPrompts = [
  { title: '正向建模', icon: MagicStick, text: '把 <数据源> 的 <源表> 做成 ODS→DWD→DIM→DWS 全链路，创建开发表、节点和调度；先给我规划，不发布生产。' },
  { title: '逆向建模', icon: Search, text: '逆向分析存量表 <请输入真实表名或节点 ID>，读取真实结构、血缘、分层和语义候选。' },
  { title: '异常排查', icon: Tools, text: '排查 DataWorks 任务 <请输入任务 ID、实例 ID 或节点 ID>，检查日志、依赖和运行底座，给出恢复建议。' },
  { title: '自主问数', icon: DataAnalysis, text: '查询 <业务指标> 今天按 <维度> 的结果；如果口径未沉淀，请先列出需要我确认的口径。' },
  { title: 'Cookie 管理', icon: Connection, text: '检查 AK/SK、官方 MCP、Cookie BFF 和 9222 调试浏览器的当前状态。' },
]
const starterPrompts = [
  { title: '一句话建完整数仓链路', description: 'ODS、DWD、DIM、DWS 建表与任务一次完成', icon: MagicStick, text: capabilityPrompts[0].text },
  { title: '逆向理解存量模型', description: '读取结构、节点、血缘并生成语义候选', icon: Search, text: capabilityPrompts[1].text },
  { title: '排查失败与数据异常', description: '汇总日志、依赖和健康状态，给恢复方案', icon: Tools, text: capabilityPrompts[2].text },
  { title: '直接问业务数据', description: '只读 SQL 护栏下自然语言查询 MaxCompute', icon: DataAnalysis, text: capabilityPrompts[3].text },
]


const modeDescriptions: Record<AgentExecutionMode, string> = {
  auto: '自动判断：能线上执行的走 dev，风险操作停在确认点',
  plan: '只生成计划和产物，不写线上环境',
  dev_execute: '允许 dev 建表/建节点；修改、删除、发布仍需确认',
}

const isRealtime = computed(() => ws.value?.readyState === WebSocket.OPEN)
const connectionText = computed(() => isRealtime.value ? '实时连接' : 'HTTP 可用')
const modeDescription = computed(() => modeDescriptions[executionMode.value])
const planSteps = computed(() => lastPayload.value?.data?.plan?.steps ?? lastPayload.value?.data?.steps ?? [])
const clarifyingQuestions = computed(() => lastPayload.value?.data?.clarifying_questions ?? [])
const composerPlaceholder = computed(() => activeClarifyingQuestion.value || '给 DataWorks Agent 发消息，例如：把 <数据源>.<源表> 做成 ODS→DWD→DWS 小时链路并初始化')
const nextActions = computed<NextActionValue[]>(() => lastPayload.value?.data?.next_actions ?? [])
const customInputHint = computed(() => lastPayload.value?.data?.allow_custom_input ? (lastPayload.value?.data?.custom_input_hint || '也可以直接在下方输入你的自定义答案。') : '')
const responseErrors = computed(() => {
  const errors = lastPayload.value?.data?.errors ?? []
  const primary = lastPayload.value?.error
  return [...new Set([...(Array.isArray(errors) ? errors.map(String) : []), ...(primary ? [primary] : [])])].slice(0, 3)
})
const publishRequest = computed(() => lastPayload.value?.data?.publish_request as Record<string, unknown> | undefined)
const publishRequestStatusText = computed(() => {
  if (publishRequest.value?.deployment_status === 'deployed') return '已人工批准并发布'
  if (publishRequest.value?.deployment_status === 'failed') return '发布失败，可重新批准重试'
  if (publishRequest.value?.status === 'rejected') return '已拒绝，未发布'
  if (publishRequest.value?.status === 'approved') return '已批准'
  return '等待人工审批'
})
const agentMode = computed(() => {
  if (publishRequest.value?.deployment_status === 'deployed') return 'executed'
  if (publishRequest.value?.status === 'rejected') return 'rejected'
  return lastPayload.value?.data?.agent_mode ?? (lastPayload.value?.success ? 'executed' : 'idle')
})
const modeText = computed(() => ({ idle: '等待目标', proposal: '计划完成', needs_context: '待确认', approval_required: '等待审批', blocked: '执行受阻', rejected: '已拒绝', executed: '开发完成' }[agentMode.value] ?? agentMode.value))
const resultTitle = computed(() => lastPayload.value?.data?.plan?.summary || lastPayload.value?.message || 'Agent 执行结果')
const stepSummary = computed(() => summarizeAgentSteps(planSteps.value))
const completedStepCount = computed(() => planSteps.value.length ? stepSummary.value.completed : (currentStatus.value?.completed_steps ?? 0))
const stepMetricValue = computed(() => planSteps.value.length ? `${completedStepCount.value}/${planSteps.value.length}` : '—')
const stepMetricLabel = computed(() => stepSummary.value.planned ? `已执行 · ${stepSummary.value.planned} 已规划` : '步骤完成')
const publishGateText = computed(() => {
  if (publishRequest.value?.deployment_status === 'deployed') return '已发布'
  if (publishRequest.value?.deployment_status === 'failed') return '发布失败'
  if (publishRequest.value?.status === 'rejected') return '已拒绝'
  if (publishRequest.value) return '待审批'
  return lastPayload.value?.data?.publish_gate === 'approval_required' ? '待审批' : '未发布'
})
const sourceDiscovery = computed(() => buildSourceDiscoveryView(lastPayload.value?.data?.source_discovery))
const executionTables = computed(() => buildExecutionResources(lastPayload.value?.data))
const capabilityBadges = computed(() => buildCapabilityBadges(capabilities.value))
const healthyCapabilityCount = computed(() => capabilityBadges.value.filter((item) => item.online).length)
const queryResult = computed(() => lastPayload.value?.data?.query)
const queryColumns = computed(() => queryResult.value?.columns ?? [])
const queryRows = computed(() => queryResult.value?.rows ?? [])
const queryChannelText = computed(() => queryResult.value?.execution_channel === 'cookie_bff' ? 'Cookie BFF 兜底' : 'MaxCompute AK/SK')
const semanticPlan = computed(() => {
  const plan = lastPayload.value?.data?.semantic_plan
  return plan && plan.metric_id !== 'ad_hoc_query' ? plan : null
})
const semanticMetricVersion = computed(() => semanticPlan.value ? `approved v${semanticPlan.value.metric_version ?? 1}` : '')
const semanticAlbumText = computed(() => (semanticPlan.value?.albums ?? []).map((item: any) => item.name).filter(Boolean).join('、') || '未匹配')
const semanticAlbumStatusText = computed(() => {
  const status = semanticPlan.value?.album_validation?.status
  if (status === 'direct_match') return '指标表与对账表已在专辑资产中直接命中'
  if (status === 'lineage_match') return '指标表与对账表已通过验证血缘关联'
  if (status === 'ungrounded') return '仅业务域匹配，资产未证明，已阻止执行'
  if (status === 'unavailable') return '专辑不可用，已阻止语义指标执行'
  return ''
})
const semanticValidationText = computed(() => {
  const validation = semanticPlan.value?.metadata_validation
  if (validation?.status !== 'passed') return '未通过'
  return validation.channel === 'maxcompute_ak_sk' ? '已通过 · AK/SK' : '已通过 · Cookie'
})
const semanticDimensionText = computed(() => (semanticPlan.value?.selected_dimensions ?? []).join('、'))
const semanticFilterText = computed(() => {
  const filters = semanticPlan.value?.caliber?.fixed_filters ?? {}
  return Object.entries(filters).map(([key, value]) => `${key}=${String(value)}`).join(' · ')
})
const semanticEvidence = computed(() => semanticPlan.value?.selection_evidence ?? [])
const semanticCheckLabels: Record<string, string> = {
  album_asset_grounding: '专辑资产',
  metric_column_grounding: 'DDL 字段',
  grain_grounding: '查询粒度',
  freshness_grounding: '最新分区',
  readonly_sql: '只读 SQL',
  query_executed: '真实执行',
  query_result_shape: '结果结构',
  result_reconciliation: 'DWS/DWD 对账',
}
const semanticVerificationChecks = computed(() => {
  const verification = lastPayload.value?.data?.verification as any
  return (verification?.checks ?? []).map((check: any) => ({
    name: String(check.check_name ?? ''),
    label: semanticCheckLabels[String(check.check_name ?? '')] ?? String(check.check_name ?? ''),
    passed: Boolean(check.passed),
  }))
})
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

onMounted(async () => {
  // 尝试从 localStorage 恢复 conversation_id
  const storedConvId = localStorage.getItem('conversation_id')
  if (storedConvId) {
    conversationId.value = storedConvId
    // 加载历史消息
    await loadConversationHistory()
  } else {
    resetConversation()
  }
  connectWebSocket()
  loadCapabilities()
})
onUnmounted(() => ws.value?.close())

function resetConversation() {
  conversationId.value = idempotencyKey()
  localStorage.setItem('conversation_id', conversationId.value)
  messages.value = [{ id: idempotencyKey(), text: '你好，我是 DataWorks Agent。你只需要说清业务目标，我会自动选择正向建模、逆向建模、异常排查、Cookie 管理或自主问数路径。', isUser: false, timestamp: new Date() }]
  lastPayload.value = null
  currentStatus.value = null
  input.value = ''
  activeClarifyingQuestion.value = ''
  reviewingDecision.value = ''
  publishReviewFeedback.value = ''
}
async function loadConversationHistory() {
  if (!conversationId.value) return
  try {
    const response = await fetch(`/agent/messages?conversation_id=${conversationId.value}`)
    const data = await response.json()
    if (data.messages && data.messages.length > 0) {
      messages.value = data.messages.map((msg: any) => ({
        id: idempotencyKey(),
        text: msg.content,
        isUser: msg.role === 'user',
        timestamp: new Date(msg.timestamp),
        interaction: msg.payload?.interaction as AgentInteraction | undefined,
      }))
    } else {
      // 没有历史消息，显示欢迎消息
      messages.value = [{ id: idempotencyKey(), text: '你好，我是 DataWorks Agent。你只需要说清业务目标，我会自动选择正向建模、逆向建模、异常排查、Cookie 管理或自主问数路径。', isUser: false, timestamp: new Date() }]
    }
  } catch {
    // 加载失败，显示欢迎消息
    messages.value = [{ id: idempotencyKey(), text: '你好，我是 DataWorks Agent。你只需要说清业务目标，我会自动选择正向建模、逆向建模、异常排查、Cookie 管理或自主问数路径。', isUser: false, timestamp: new Date() }]
  }
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
async function sendMessage(
  overrideText?: string,
  contextUpdates?: AgentContextUpdates,
  interactionAnswer?: InteractionAnswer,
) {
  const text = (overrideText ?? input.value).trim()
  if (!text || loading.value) return
  input.value = ''
  messages.value.push({ id: idempotencyKey(), text, isUser: true, timestamp: new Date() })
  loading.value = true
  await nextTick(scrollToBottom)
  try {
    const payload = buildAgentChatRequest(
      text,
      executionMode.value,
      initializeData.value,
      requestPublish.value,
      conversationId.value,
      contextUpdates,
      interactionAnswer,
    )
    handleAgentResponse(await requestAgentChat<AgentPayload>(payload))
  } catch (error) {
    handleAgentResponse({ message: `Agent 请求失败：${error instanceof Error ? error.message : String(error)}`, success: false })
  } finally {
    loading.value = false
  }
}
function handleAgentResponse(payload: AgentPayload) {
  lastPayload.value = payload
  publishReviewFeedback.value = ''
  if (payload.data?.capabilities) capabilities.value = payload.data.capabilities
  activeClarifyingQuestion.value = payload.data?.clarifying_questions?.[0] ?? ''
  messages.value.push({
    id: idempotencyKey(),
    text: payload.message,
    isUser: false,
    timestamp: new Date(),
    interaction: payload.data?.interaction,
  })
  currentStatus.value = payload.data?.status ?? currentStatus.value
  loading.value = false
  nextTick(scrollToBottom)
}
async function reviewPublish(decision: 'approve' | 'reject') {
  const requestId = String(publishRequest.value?.request_id ?? '')
  if (!requestId || reviewingDecision.value) return
  reviewingDecision.value = decision
  publishReviewFeedback.value = ''
  try {
    const result = await reviewPublishRequest(requestId, decision)
    if (lastPayload.value?.data) {
      lastPayload.value.data.publish_request = result.request
      lastPayload.value.data.publish_gate = result.request.deployment_status === 'deployed' ? 'deployed' : String(result.request.status ?? 'approval_required')
      lastPayload.value.data.agent_mode = result.request.deployment_status === 'deployed' ? 'executed' : result.request.status === 'rejected' ? 'rejected' : 'approval_required'
    }
    publishReviewFeedback.value = result.message
    messages.value.push({ id: idempotencyKey(), text: result.message, isUser: false, timestamp: new Date() })
  } catch (error) {
    publishReviewFeedback.value = `审批操作失败：${error instanceof Error ? error.message : String(error)}`
  } finally {
    reviewingDecision.value = ''
    nextTick(scrollToBottom)
  }
}
function selectPrompt(text: string) { input.value = text; nextTick(() => composerInput.value?.focus()) }
function nextActionLabel(action: NextActionValue) { return typeof action === 'string' ? action : action.label }
function nextActionKey(action: NextActionValue) { return typeof action === 'string' ? action : action.id }
function chooseNextAction(action: NextActionValue) {
  if (typeof action === 'string') {
    return selectPrompt(action)
  }
  if (action.requires_custom_input) {
    activeClarifyingQuestion.value = customInputHint.value || action.label
    input.value = ''
    nextTick(() => composerInput.value?.focus())
    return
  }
  void sendMessage(action.label, action.payload)
}
function prepareClarification(question: string) {
  activeClarifyingQuestion.value = question
  input.value = ''
  nextTick(() => composerInput.value?.focus())
}
function scrollToBottom() { if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight }
function stepStatus(step: PlanStep, index: number) { return agentStepMarker(step, index) }
function phaseLabel(phase?: string) { return ({ understand: '理解目标', inspect: '检查环境', plan: '生成计划', design: '设计模型', orchestrate: '编排任务', guardrail: '安全检查', execute: '开发执行' }[phase ?? ''] ?? '执行步骤') }
function humanizeStep(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase()) }
function queryCell(row: unknown[] | Record<string, unknown>, column: string, columnIndex: number) {
  const value = Array.isArray(row) ? row[columnIndex] : row[column]
  return value === null || value === undefined ? '—' : String(value)
}
function artifactLabel(key: string) { return ({ ddl: 'DDL', sql: 'DML / SQL', query_sql: '只读查询 SQL', node_sql: '节点 SQL', table_schema: '表结构', semantic_candidates: '语义候选', semantic_query_plan: '语义查询计划' }[key] ?? key.replaceAll('_', ' ')) }
</script>

<style scoped>
/* Layout */
.agent-workspace { height: calc(100vh - 60px - 32px); min-height: 0; display: grid; grid-template-columns: 220px minmax(0, 1fr); overflow: hidden; background: var(--color-bg-card); border-radius: var(--radius-lg); border: 1px solid var(--color-border-primary); }

/* Rail */
.conversation-rail { display: flex; flex-direction: column; padding: var(--space-4) var(--space-3); border-right: 1px solid var(--color-border-secondary); background: var(--color-bg-secondary); }
.new-chat-btn { height: 40px; display: flex; align-items: center; justify-content: center; gap: 8px; border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); color: var(--color-text-secondary); font-weight: 600; font-size: var(--font-size-sm); cursor: pointer; transition: all var(--transition-fast); }
.new-chat-btn:hover { border-color: var(--color-accent-blue); color: var(--color-accent-blue); background: var(--gradient-subtle); }
.rail-section { margin-top: var(--space-5); }
.rail-label { display: block; padding: 0 var(--space-3) var(--space-2); color: var(--color-text-tertiary); font-size: var(--font-size-xs); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
.rail-item { width: 100%; height: 38px; display: flex; align-items: center; gap: 10px; padding: 0 var(--space-3); border: 0; border-radius: var(--radius-md); background: transparent; color: var(--color-text-secondary); font-size: var(--font-size-sm); cursor: pointer; text-align: left; transition: all var(--transition-fast); }
.rail-item:hover { color: var(--color-text-primary); background: var(--color-bg-hover); }
.rail-item .el-icon { color: var(--color-text-tertiary); font-size: 16px; }
.rail-bottom { margin-top: auto; }
.runtime-card { padding: var(--space-3); border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); }
.runtime-title { display: flex; align-items: center; gap: 8px; color: var(--color-text-primary); font-size: var(--font-size-xs); font-weight: 700; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-text-tertiary); }
.status-dot.online { background: var(--color-accent-green); box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.2); }
.runtime-grid { display: flex; flex-wrap: wrap; gap: 6px; margin: var(--space-3) 0 var(--space-2); }
.runtime-grid span { padding: 3px 8px; border-radius: var(--radius-sm); background: var(--color-bg-secondary); color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.runtime-grid span.online { background: rgba(52, 211, 153, 0.15); color: var(--color-accent-green); }
.runtime-card small { color: var(--color-text-tertiary); font-size: var(--font-size-xs); }

/* Main chat */
.conversation-main { min-width: 0; min-height: 0; overflow: hidden; display: grid; grid-template-rows: 60px minmax(0,1fr) auto; background: var(--color-bg-card); }
.chat-header { display: flex; align-items: center; justify-content: space-between; padding: 0 var(--space-5); border-bottom: 1px solid var(--color-border-secondary); }
.product-row { display: flex; align-items: center; gap: 10px; }
.product-row strong { color: var(--color-text-primary); font-size: var(--font-size-md); font-weight: 700; }
.edition { padding: 3px 8px; border-radius: var(--radius-sm); background: var(--gradient-subtle); color: var(--color-accent-blue); font-size: var(--font-size-xs); font-weight: 700; }
.chat-header p { margin: 2px 0 0 44px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.header-actions { display: flex; align-items: center; gap: 8px; }
.connection-pill { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid var(--color-border-primary); border-radius: var(--radius-full); color: var(--color-text-secondary); font-size: var(--font-size-xs); font-weight: 600; }
.conn-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-accent-orange); }
.conn-dot.online { background: var(--color-accent-green); }

.message-stage { min-height: 0; overflow-y: auto; scrollbar-width: thin; }
.message-stage.empty { display: grid; place-items: center; }

/* Welcome panel */
.welcome-panel { width: min(680px, calc(100% - 48px)); padding: var(--space-8) 0 var(--space-12); text-align: center; }
.agent-orb { width: 56px; height: 56px; display: grid; place-items: center; margin: 0 auto var(--space-5); border-radius: var(--radius-xl); background: var(--gradient-brand); color: #fff; font-size: 24px; box-shadow: 0 12px 32px rgba(96, 165, 250, 0.3); }
.welcome-panel h1 { margin: 0; color: var(--color-text-primary); font-size: 28px; font-weight: 700; letter-spacing: -0.02em; }
.welcome-panel > p { margin: var(--space-3) auto var(--space-6); max-width: 540px; color: var(--color-text-secondary); font-size: var(--font-size-md); line-height: 1.7; }
.prompt-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-3); text-align: left; }
.prompt-grid button { position: relative; min-height: 88px; display: grid; grid-template-columns: 36px 1fr 20px; grid-template-rows: auto auto; column-gap: 10px; align-items: center; padding: var(--space-4); border: 1px solid var(--color-border-primary); border-radius: var(--radius-lg); background: var(--color-bg-tertiary); cursor: pointer; transition: all var(--transition-fast); }
.prompt-grid button:hover { border-color: var(--color-border-active); transform: translateY(-2px); box-shadow: var(--shadow-glow); }
.prompt-icon { grid-row: 1/3; width: 36px; height: 36px; display: grid; place-items: center; border-radius: var(--radius-md); background: var(--gradient-subtle); color: var(--color-accent-blue); }
.prompt-grid strong { color: var(--color-text-primary); font-size: var(--font-size-sm); font-weight: 600; }
.prompt-grid small { color: var(--color-text-secondary); font-size: var(--font-size-xs); line-height: 1.4; }
.prompt-arrow { grid-column: 3; grid-row: 1/3; color: var(--color-text-tertiary); }

/* Message list */
.message-list { width: min(860px, calc(100% - 48px)); margin: 0 auto; padding: var(--space-6) 0 var(--space-8); }
.thinking-row { display: flex; gap: 12px; margin: var(--space-2) 0 var(--space-5); align-items: center; }
.thinking-dots { display: flex; gap: 4px; }
.thinking-dots span { width: 6px; height: 6px; border-radius: 50%; background: var(--color-accent-blue); animation: pulse 1s infinite alternate; }
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
.thinking-row em { margin-left: 6px; font-size: var(--font-size-xs); color: var(--color-text-tertiary); font-style: normal; }

/* Result card */
.result-card { margin: var(--space-4) 0 var(--space-5); overflow: hidden; border: 1px solid var(--color-border-primary); border-radius: var(--radius-lg); background: var(--color-bg-secondary); }
.result-header { display: flex; justify-content: space-between; gap: var(--space-4); padding: var(--space-4); border-bottom: 1px solid var(--color-border-secondary); }
.result-kicker { color: var(--color-text-tertiary); font-size: var(--font-size-xs); font-weight: 800; letter-spacing: 0.12em; }
.result-card h3 { max-width: 600px; margin: var(--space-1) 0 0; color: var(--color-text-primary); font-size: var(--font-size-sm); line-height: 1.5; }
.result-state { height: fit-content; padding: 4px 10px; border-radius: var(--radius-sm); background: rgba(52, 211, 153, 0.15); color: var(--color-accent-green); font-size: var(--font-size-xs); font-weight: 700; }
.result-state.blocked { background: rgba(248, 113, 113, 0.15); color: var(--color-accent-red); }
.result-state.approval_required, .result-state.needs_context { background: rgba(251, 191, 36, 0.15); color: var(--color-accent-orange); }

.result-metrics { display: grid; grid-template-columns: repeat(4, 1fr); border-bottom: 1px solid var(--color-border-secondary); }
.result-metrics div { padding: var(--space-3) var(--space-4); border-right: 1px solid var(--color-border-secondary); }
.result-metrics div:last-child { border-right: 0; }
.result-metrics strong, .result-metrics span { display: block; }
.result-metrics strong { color: var(--color-text-primary); font-size: var(--font-size-lg); }
.result-metrics span { margin-top: 4px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }

.compact-plan { margin: 0; padding: var(--space-4); list-style: none; }
.compact-plan li { display: flex; align-items: center; gap: 10px; min-height: 36px; }
.step-check { width: 22px; height: 22px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 50%; background: var(--gradient-subtle); color: var(--color-accent-blue); font-size: var(--font-size-xs); font-weight: 800; }
.step-check.step-failed, .step-check.step-error, .step-check.step-blocked { background: rgba(248, 113, 113, 0.15); color: var(--color-accent-red); }
.step-check.step-warning { background: rgba(251, 191, 36, 0.15); color: var(--color-accent-orange); }
.step-check.step-skipped { background: var(--color-bg-tertiary); color: var(--color-text-tertiary); }
.compact-plan strong, .compact-plan small { display: block; }
.compact-plan strong { color: var(--color-text-primary); font-size: var(--font-size-xs); }
.compact-plan small { margin-top: 2px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }

.created-resources { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 var(--space-4) var(--space-4); }
.created-resources span { padding: 4px 8px; border: 1px solid var(--color-border-primary); border-radius: var(--radius-sm); color: var(--color-text-secondary); font-family: var(--font-family-mono); font-size: var(--font-size-xs); }

/* Query result */
.query-result { margin: 0 var(--space-4) var(--space-4); overflow: hidden; border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); }
.query-result-title { display: flex; align-items: center; justify-content: space-between; padding: var(--space-2) var(--space-3); background: var(--gradient-subtle); color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.query-result-title strong { color: var(--color-accent-blue); font-size: var(--font-size-xs); }
.query-table-wrap { max-height: 280px; overflow: auto; }
.query-result table { width: 100%; border-collapse: collapse; font-size: var(--font-size-xs); white-space: nowrap; }
.query-result th, .query-result td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-border-secondary); text-align: left; }
.query-result th { position: sticky; top: 0; background: var(--color-bg-secondary); color: var(--color-text-secondary); font-weight: 600; }
.query-result td { color: var(--color-text-primary); }

/* Semantic proof */
.semantic-proof { margin: var(--space-3) var(--space-4) 0; padding: var(--space-3); border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); }
.semantic-proof-title { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.semantic-proof-title div { display: flex; flex-direction: column; gap: 4px; }
.semantic-proof-title strong { color: var(--color-text-primary); font-size: var(--font-size-sm); }
.semantic-proof-title div span { color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.semantic-proof-title > span { padding: 3px 8px; border-radius: var(--radius-sm); background: rgba(96, 165, 250, 0.15); color: var(--color-accent-blue); font-size: var(--font-size-xs); font-weight: 700; }
.semantic-proof-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: var(--space-3); }
.semantic-proof-grid div { min-width: 0; padding: var(--space-2); border-radius: var(--radius-sm); background: var(--color-bg-secondary); }
.semantic-proof-grid small, .semantic-proof-row small { display: block; margin-bottom: 4px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.semantic-proof-grid strong { display: block; overflow: hidden; color: var(--color-text-primary); font-size: var(--font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
.semantic-proof-row { margin-top: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.semantic-proof-row code { white-space: normal; word-break: break-all; }
.semantic-proof ul { margin: 8px 0 0; padding-left: var(--space-4); color: var(--color-text-secondary); font-size: var(--font-size-xs); line-height: 1.6; }
.semantic-checks { display: flex; flex-wrap: wrap; gap: 6px; margin-top: var(--space-2); }
.semantic-checks span { padding: 3px 8px; border-radius: var(--radius-sm); background: rgba(248, 113, 113, 0.15); color: var(--color-accent-red); font-size: var(--font-size-xs); }
.semantic-checks span.passed { background: rgba(52, 211, 153, 0.15); color: var(--color-accent-green); }

/* Source discovery */
.source-discovery { margin: var(--space-3) var(--space-4); padding: var(--space-3); border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); }
.source-discovery.success { border-color: rgba(52, 211, 153, 0.3); background: rgba(52, 211, 153, 0.05); }
.source-discovery-title { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.source-discovery-title div strong { display: block; color: var(--color-text-primary); font-size: var(--font-size-xs); }
.source-discovery.success .source-discovery-title div strong { color: var(--color-accent-green); }
.source-discovery-title div span { display: block; margin-top: 4px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.source-discovery-title > span { padding: 3px 8px; border-radius: var(--radius-full); background: rgba(251, 191, 36, 0.15); color: var(--color-accent-orange); font-size: var(--font-size-xs); }
.source-discovery.success .source-discovery-title > span { background: rgba(52, 211, 153, 0.15); color: var(--color-accent-green); }
.source-discovery-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: var(--space-3); }
.source-discovery-grid div { min-width: 0; padding: var(--space-2); border-radius: var(--radius-sm); background: var(--color-bg-secondary); }
.source-discovery-grid small { display: block; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.source-discovery-grid strong { display: block; overflow: hidden; margin-top: 4px; color: var(--color-text-primary); font-size: var(--font-size-xs); text-overflow: ellipsis; white-space: nowrap; }
.source-discovery-evidence { display: flex; flex-wrap: wrap; gap: var(--space-3); margin-top: var(--space-2); color: var(--color-accent-green); font-size: var(--font-size-xs); }
.source-discovery-blocker { margin-top: var(--space-2); padding: var(--space-2); border-radius: var(--radius-sm); background: var(--color-bg-secondary); }
.source-discovery-blocker > strong { color: var(--color-accent-orange); font-size: var(--font-size-xs); }
.source-discovery-blocker p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: var(--font-size-xs); line-height: 1.5; }
.source-discovery-blocker b { color: var(--color-accent-orange); }

/* Publish approval */
.publish-approval { margin: var(--space-3) var(--space-4); padding: var(--space-3); border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); }
.publish-approval-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.publish-approval-head div small { display: block; color: var(--color-text-tertiary); font-size: var(--font-size-xs); font-weight: 800; letter-spacing: 0.08em; }
.publish-approval-head div strong { color: var(--color-text-primary); font-size: var(--font-size-sm); }
.publish-approval-head span { padding: 3px 8px; border-radius: var(--radius-sm); background: rgba(251, 191, 36, 0.15); color: var(--color-accent-orange); font-size: var(--font-size-xs); }
.publish-approval p { margin: 8px 0 0; color: var(--color-text-secondary); font-size: var(--font-size-xs); line-height: 1.5; }
.publish-actions { display: flex; gap: var(--space-2); margin-top: var(--space-2); }
.approve-button { padding: 6px 14px; border: 0; border-radius: var(--radius-sm); background: var(--color-accent-green); color: #fff; font-size: var(--font-size-xs); font-weight: 600; cursor: pointer; transition: all var(--transition-fast); }
.approve-button:hover { opacity: 0.9; }
.approve-button:disabled { background: rgba(52, 211, 153, 0.3); cursor: not-allowed; }
.reject-button { padding: 6px 14px; border: 1px solid var(--color-border-primary); border-radius: var(--radius-sm); background: var(--color-bg-secondary); color: var(--color-text-secondary); font-size: var(--font-size-xs); font-weight: 600; cursor: pointer; transition: all var(--transition-fast); }
.reject-button:hover { border-color: var(--color-accent-red); color: var(--color-accent-red); }
.reject-button:disabled { background: var(--color-bg-tertiary); color: var(--color-text-tertiary); cursor: not-allowed; }
.publish-feedback { margin-top: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); }

/* Errors */
.response-errors { margin-top: var(--space-3); padding: var(--space-3); border: 1px solid rgba(248, 113, 113, 0.3); border-radius: var(--radius-md); background: rgba(248, 113, 113, 0.08); color: var(--color-accent-red); }
.response-errors strong, .next-actions strong { display: block; margin-bottom: 6px; font-size: var(--font-size-xs); }
.response-errors p { margin: 4px 0; font-size: var(--font-size-xs); line-height: 1.5; word-break: break-word; }

/* Next actions */
.next-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: var(--space-3); }
.next-actions button { padding: 6px 12px; border: 1px solid var(--color-border-primary); border-radius: var(--radius-sm); background: var(--color-bg-tertiary); color: var(--color-accent-blue); font-size: var(--font-size-xs); cursor: pointer; transition: all var(--transition-fast); }
.next-actions button:hover { border-color: var(--color-border-active); background: var(--gradient-subtle); }
.next-actions button:disabled { background: var(--color-bg-secondary); color: var(--color-text-tertiary); cursor: not-allowed; }
.custom-input-hint { display: block; width: 100%; margin-top: 6px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }

/* Question card */
.question-card { margin: var(--space-3) 0 var(--space-4) 44px; padding: var(--space-4); border: 1px solid var(--color-border-primary); border-radius: var(--radius-md); background: var(--color-bg-tertiary); }
.question-card > strong { display: block; margin-bottom: 8px; color: var(--color-text-primary); font-size: var(--font-size-xs); }
.question-card button { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border: 0; border-top: 1px solid var(--color-border-secondary); background: transparent; color: var(--color-text-secondary); font-size: var(--font-size-xs); cursor: pointer; text-align: left; }

/* Technical collapse */
.technical-collapse { border-top: 1px solid var(--color-border-secondary); padding: 0 var(--space-4); }
.technical-collapse :deep(.el-collapse-item__header) { font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.artifact-list article { margin-bottom: var(--space-2); }
.artifact-list strong { color: var(--color-text-secondary); font-size: var(--font-size-xs); }
.artifact-list pre, .json-detail { max-height: 220px; overflow: auto; padding: var(--space-3); border-radius: var(--radius-sm); background: var(--color-bg-primary); color: var(--color-text-primary); font-size: var(--font-size-xs); white-space: pre-wrap; font-family: var(--font-family-mono); }
.artifact-list p { color: var(--color-text-secondary); font-size: var(--font-size-xs); white-space: pre-wrap; }

/* Composer */
.composer-shell { min-height: 0; flex-shrink: 0; padding: var(--space-3) var(--space-5) var(--space-4); background: linear-gradient(180deg, transparent, var(--color-bg-card) 20%); }
.composer-box { width: min(860px, 100%); margin: 0 auto; overflow: hidden; border: 1px solid var(--color-border-primary); border-radius: var(--radius-lg); background: var(--color-bg-secondary); box-shadow: var(--shadow-md); transition: all var(--transition-fast); }
.composer-box.focused { border-color: var(--color-accent-blue); box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.15), var(--shadow-md); }
.composer-box textarea { width: 100%; min-height: 48px; max-height: 140px; box-sizing: border-box; resize: none; padding: var(--space-4) var(--space-4) var(--space-2); border: 0; outline: 0; background: transparent; color: var(--color-text-primary); font: var(--font-size-base)/1.6 inherit; }
.composer-box textarea::placeholder { color: var(--color-text-tertiary); }
.composer-toolbar { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-2) var(--space-3) var(--space-3) var(--space-4); }
.mode-control { display: flex; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: var(--font-size-xs); font-weight: 600; }
.execution-warning { padding: 4px 8px; border: 1px solid rgba(251, 191, 36, 0.3); border-radius: var(--radius-sm); background: rgba(251, 191, 36, 0.1); color: var(--color-accent-orange); font-size: var(--font-size-xs); }
.guard-hint { display: flex; align-items: center; gap: 4px; color: var(--color-text-tertiary); font-size: var(--font-size-xs); }
.send-button { width: 32px; height: 32px; display: grid; place-items: center; margin-left: auto; border: 0; border-radius: var(--radius-md); background: var(--gradient-brand); color: #fff; cursor: pointer; transition: all var(--transition-fast); box-shadow: 0 2px 8px rgba(96, 165, 250, 0.3); }
.send-button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(96, 165, 250, 0.4); }
.send-button:disabled { background: var(--color-bg-tertiary); color: var(--color-text-tertiary); cursor: not-allowed; box-shadow: none; transform: none; }
.send-spinner { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.8s linear infinite; }
.composer-shell > p { margin: 8px 0 0; color: var(--color-text-tertiary); font-size: var(--font-size-xs); text-align: center; }

@keyframes pulse { to { opacity: 0.25; transform: translateY(-2px); } }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 900px) {
  .source-discovery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .agent-workspace { grid-template-columns: 1fr; }
  .conversation-rail { display: none; }
  .result-metrics { grid-template-columns: repeat(2, 1fr); }
  .result-metrics div:nth-child(2) { border-right: 0; }
  .prompt-grid { grid-template-columns: 1fr; }
  .chat-header { padding: 0 var(--space-4); }
  .composer-shell { padding-left: var(--space-3); padding-right: var(--space-3); }
  .message-list { width: calc(100% - 24px); }
  .welcome-panel { width: calc(100% - 24px); }
}
</style>
