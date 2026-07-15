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

      <div class="rail-section policy-stack">
        <article class="boundary-card">
          <span class="rail-label">执行边界</span>
          <ul>
            <li v-for="item in executionBoundary" :key="item.label" :class="item.tone">
              <strong>{{ item.label }}</strong><small>{{ item.detail }}</small>
            </li>
          </ul>
        </article>
        <article class="boundary-card knowledge-card">
          <span class="rail-label">知识边界</span>
          <p>通用能力走线上产品；私有指标、目录和业务词沉淀到本地知识库。</p>
        </article>
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
          <small>{{ healthyCapabilityCount }}/{{ capabilityBadges.length }} 条通道就绪</small>
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
          <p>一句话完成通用建模、诊断、问数和审批编排；私有知识不硬编码进产品。</p>
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
          <p>直接描述业务目标。Agent 负责自动编排执行路径，改节点、删节点和生产发布会停在确认点。</p>
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

            <section
              v-if="sourceDiscovery.visible"
              class="source-discovery"
              :class="{ success: sourceDiscovery.success }"
              data-testid="source-discovery"
            >
              <div class="source-discovery-title">
                <div><strong>OSS 字段探测</strong><span>优先复用 DataWorks 托管元数据，不展示或保存样本正文</span></div>
                <span>{{ sourceDiscovery.statusText }}</span>
              </div>
              <div class="source-discovery-grid">
                <div><small>探测通道</small><strong>{{ sourceDiscovery.channelText }}</strong></div>
                <div v-if="sourceDiscovery.datasourceName"><small>托管数据源</small><strong>{{ sourceDiscovery.datasourceName }}</strong></div>
                <div v-if="sourceDiscovery.metadataSourceText"><small>元数据来源</small><strong>{{ sourceDiscovery.metadataSourceText }}</strong></div>
                <div v-if="sourceDiscovery.showEndpoint"><small>请求 Endpoint</small><strong>{{ sourceDiscovery.endpoint }}</strong></div>
                <div v-if="sourceDiscovery.showEndpoint"><small>实际 Endpoint</small><strong>{{ sourceDiscovery.endpointUsed || '-' }}</strong></div>
                <div><small>Bucket</small><strong>{{ sourceDiscovery.bucket }}</strong></div>
                <div><small>Prefix</small><strong>{{ sourceDiscovery.prefix }}</strong></div>
                <div><small>文件格式</small><strong>{{ sourceDiscovery.fileFormat }}</strong></div>
                <div><small>字段数量</small><strong>{{ sourceDiscovery.columnCount }}</strong></div>
              </div>
              <div v-if="sourceDiscovery.success" class="source-discovery-evidence">
                <span v-if="sourceDiscovery.sampleObject">样本对象：{{ sourceDiscovery.sampleObject }}</span>
                <span v-if="sourceDiscovery.channel === 'local_oss_sdk'">采样记录：{{ sourceDiscovery.recordCount }}</span>
                <span>未展示或保存样本正文</span>
              </div>
              <div v-else class="source-discovery-blocker">
                <strong>{{ sourceDiscovery.errorCode || 'schema_discovery_failed' }}</strong>
                <p>{{ sourceDiscovery.error || '字段探测尚未完成。' }}</p>
                <p v-if="sourceDiscovery.nextAction"><b>下一步：</b>{{ sourceDiscovery.nextAction }}</p>
                <small v-if="sourceDiscovery.attemptedEndpoints.length">已尝试：{{ sourceDiscovery.attemptedEndpoints.join(' → ') }}</small>
              </div>
            </section>

            <div v-if="executionTables.length" class="created-resources">
              <span v-for="resource in executionTables" :key="resource">{{ resource }}</span>
            </div>

            <section v-if="publishRequest" class="publish-approval" data-testid="publish-approval">
              <div class="publish-approval-head">
                <div>
                  <small>PUBLISH GATE</small>
                  <strong>{{ publishRequestStatusText }}</strong>
                </div>
                <span>{{ String(publishRequest.table_name || '待发布节点') }}</span>
              </div>
              <p>开发表、节点与调度已保存为草稿。只有点击“批准并发布”后，Agent 才会调用 DataWorks 发布接口。</p>
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

            <div v-if="responseErrors.length" class="response-errors">
              <strong>执行受阻</strong>
              <p v-for="error in responseErrors" :key="error">{{ error }}</p>
            </div>

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
            <button v-for="question in clarifyingQuestions" :key="question" type="button" @click="prepareClarification(question)">
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
            :placeholder="composerPlaceholder"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
            @keydown.enter.exact.prevent="() => void sendMessage()"
          />
          <div class="composer-toolbar">
            <div class="mode-control">
              <span>执行模式</span>
              <el-segmented v-model="executionMode" :options="modeOptions" size="small" />
            </div>
            <span v-if="executionMode === 'dev_execute'" class="execution-warning">仅开发环境写入；改/删/发布会先停下确认</span>
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
            <span class="guard-hint"><el-icon><Lock /></el-icon>{{ modeDescription }}</span>
            <button class="send-button" type="button" :disabled="!input.trim() || loading" @click="() => void sendMessage()">
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
import { buildSourceDiscoveryView } from './sourceDiscovery'
import { buildExecutionResources } from './executionResources'
import { buildAgentChatRequest, requestAgentChat, reviewPublishRequest, type AgentContextUpdates, type AgentExecutionMode } from './chatInteraction'
import { idempotencyKey } from '@/utils/request'

interface ChatMsg { id: string; text: string; isUser: boolean; timestamp: Date }
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

const input = ref('')
const reviewingDecision = ref<'' | 'approve' | 'reject'>('')
const publishReviewFeedback = ref('')
const inputFocused = ref(false)
const activeClarifyingQuestion = ref('')
const loading = ref(false)
const executionMode = ref<AgentExecutionMode>('auto')
const initializeData = ref(true)
const requestPublish = ref(false)
const conversationId = ref(idempotencyKey())
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

const executionBoundary = [
  { label: 'Dev 建表', detail: '允许自动执行', tone: 'allow' },
  { label: 'Dev 建节点', detail: '允许自动执行', tone: 'allow' },
  { label: '改已有节点', detail: '执行前确认', tone: 'confirm' },
  { label: '删除节点', detail: '执行前确认', tone: 'confirm' },
  { label: '生产发布', detail: '人工确认', tone: 'manual' },
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

onMounted(() => {
  resetConversation()
  connectWebSocket()
  loadCapabilities()
})
onUnmounted(() => ws.value?.close())

function resetConversation() {
  conversationId.value = idempotencyKey()
  messages.value = [{ id: idempotencyKey(), text: '你好，我是 DataWorks Agent。你只需要说清业务目标，我会自动选择正向建模、逆向建模、异常排查、Cookie 管理或自主问数路径。', isUser: false, timestamp: new Date() }]
  lastPayload.value = null
  currentStatus.value = null
  input.value = ''
  activeClarifyingQuestion.value = ''
  reviewingDecision.value = ''
  publishReviewFeedback.value = ''
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
async function sendMessage(overrideText?: string, contextUpdates?: AgentContextUpdates) {
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
  messages.value.push({ id: idempotencyKey(), text: payload.message, isUser: false, timestamp: new Date() })
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
.agent-workspace { height: calc(100vh - 66px); min-height: 0; display: grid; grid-template-columns: 220px minmax(0, 1fr); overflow: hidden; background: #fff; border: 1px solid #e8e8eb; border-radius: 14px; box-shadow: 0 2px 12px rgba(0,0,0,.035); }
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
.conversation-main { min-width: 0; min-height: 0; overflow: hidden; display: grid; grid-template-rows: 66px minmax(0,1fr) auto; background: #fff; }
.chat-header { display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid #ededf0; }
.product-row { display: flex; align-items: center; gap: 9px; color: #202123; }.product-mark,.thinking-mark { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; background: linear-gradient(145deg,#7658ff,#5c3ef2); color: #fff; font-weight: 800; }.edition { padding: 3px 7px; border-radius: 5px; background: #f0edff; color: #6748ef; font-size: 10px; font-weight: 700; }.chat-header p { margin: 3px 0 0 37px; color: #9a9aa1; font-size: 11px; }
.header-actions { display: flex; align-items: center; gap: 5px; }.connection-pill { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border: 1px solid #e4e4e8; border-radius: 999px; color: #707078; font-size: 11px; }.connection-pill i { width: 6px; height: 6px; border-radius: 50%; background: #e6a23c; }.connection-pill i.online { background: #20b26b; }
.message-stage { min-height: 0; overflow-y: auto; scrollbar-width: thin; }.message-stage.empty { display: grid; place-items: center; }
.welcome-panel { width: min(760px, calc(100% - 48px)); padding: 34px 0 50px; text-align: center; }.agent-orb { width: 54px; height: 54px; display: grid; place-items: center; margin: 0 auto 18px; border-radius: 17px; background: linear-gradient(145deg,#7658ff,#5034de); color: #fff; font-size: 24px; box-shadow: 0 12px 30px rgba(91,61,226,.22); }.welcome-panel h1 { margin: 0; color: #202123; font-size: 28px; letter-spacing: -.035em; }.welcome-panel>p { margin: 11px auto 28px; max-width: 600px; color: #85858c; font-size: 14px; line-height: 1.7; }
.prompt-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 10px; text-align: left; }.prompt-grid button { position: relative; min-height: 92px; display: grid; grid-template-columns: 34px 1fr 20px; grid-template-rows: auto auto; column-gap: 10px; align-items: center; padding: 15px; border: 1px solid #e4e4e8; border-radius: 11px; background: #fff; cursor: pointer; transition: .2s; }.prompt-grid button:hover { border-color: #b9abff; transform: translateY(-1px); box-shadow: 0 8px 22px rgba(49,38,102,.08); }.prompt-icon { grid-row: 1/3; width: 34px; height: 34px; display: grid; place-items: center; border-radius: 9px; background: #f1eeff; color: #694af0; }.prompt-grid strong { color: #303036; font-size: 13px; }.prompt-grid small { color: #929299; font-size: 11px; line-height: 1.4; }.prompt-arrow { grid-column: 3; grid-row: 1/3; color: #b4b4ba; }
.message-list { width: min(900px, calc(100% - 48px)); margin: 0 auto; padding: 28px 0 36px; }.thinking-row { display: flex; gap: 12px; margin: 8px 0 22px; }.thinking-row>div { display: flex; align-items: center; gap: 4px; color: #888890; }.thinking-row i { width: 5px; height: 5px; border-radius: 50%; background: #7456f5; animation: pulse 1s infinite alternate; }.thinking-row i:nth-child(2){animation-delay:.2s}.thinking-row i:nth-child(3){animation-delay:.4s}.thinking-row em { margin-left: 6px; font-size: 12px; font-style: normal; }
.result-card { margin: 16px 0 24px 40px; overflow: hidden; border: 1px solid #e1e1e5; border-radius: 12px; background: #fff; }.result-card>header { display: flex; justify-content: space-between; gap: 18px; padding: 18px 20px; border-bottom: 1px solid #ededf0; }.result-kicker { color: #9a9aa1; font-size: 9px; font-weight: 800; letter-spacing: .12em; }.result-card h3 { max-width: 650px; margin: 5px 0 0; color: #29292f; font-size: 14px; line-height: 1.5; }.result-state { height: fit-content; padding: 5px 9px; border-radius: 6px; background: #ecf8f2; color: #168552; font-size: 11px; font-weight: 700; }.result-state.blocked { background: #fff0f0; color: #d14343; }.result-state.approval_required,.result-state.needs_context { background: #fff6e8; color: #b66a00; }
.result-metrics { display: grid; grid-template-columns: repeat(4,1fr); border-bottom: 1px solid #ededf0; }.result-metrics div { padding: 14px 18px; border-right: 1px solid #ededf0; }.result-metrics div:last-child { border-right: 0; }.result-metrics strong,.result-metrics span { display: block; }.result-metrics strong { color: #27272d; font-size: 16px; }.result-metrics span { margin-top: 3px; color: #9a9aa1; font-size: 10px; }
.compact-plan { margin: 0; padding: 16px 20px; list-style: none; }.compact-plan li { display: flex; align-items: center; gap: 10px; min-height: 38px; }.step-check { width: 22px; height: 22px; display: grid; place-items: center; flex: 0 0 auto; border-radius: 50%; background: #eeebff; color: #6748ef; font-size: 10px; font-weight: 800; }.step-check.step-failed,.step-check.step-error,.step-check.step-blocked { background: #fff0f0; color: #d14343; } .step-check.step-warning { background: #fff6e8; color: #b66a00; } .step-check.step-skipped { background: #f0f0f2; color: #8b8b92; } .step-check.step-approval_required { background: #fff6e8; color: #b66a00; } .compact-plan strong,.compact-plan small { display: block; }.compact-plan strong { color: #4b4b52; font-size: 12px; }.compact-plan small { margin-top: 2px; color: #a2a2a8; font-size: 10px; }.created-resources { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 20px 16px; }.created-resources span { padding: 5px 8px; border: 1px solid #dedee3; border-radius: 6px; color: #5d5d65; font-family: ui-monospace,monospace; font-size: 10px; }
.query-result { margin: 0 20px 16px; overflow: hidden; border: 1px solid #e4e1f6; border-radius: 10px; background: #fff; }.query-result-title { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; background: #f8f7ff; color: #55555d; font-size: 11px; }.query-result-title strong { color: #382a7d; font-size: 12px; }.query-table-wrap { max-height: 320px; overflow: auto; }.query-result table { width: 100%; border-collapse: collapse; font-size: 11px; white-space: nowrap; }.query-result th,.query-result td { padding: 8px 10px; border-bottom: 1px solid #eeeef2; text-align: left; }.query-result th { position: sticky; top: 0; background: #fff; color: #666670; font-weight: 600; }.query-result td { color: #33333a; }
.semantic-proof { margin: 14px 20px 0; padding: 14px; border: 1px solid #dfe8ff; border-radius: 10px; background: #f8faff; }
.semantic-proof-title { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }.semantic-proof-title div { display:flex; flex-direction:column; gap:3px; }.semantic-proof-title strong { color:#252536; font-size:13px; }.semantic-proof-title div span { color:#7b7b87; font-size:10px; }.semantic-proof-title>span { padding:3px 7px; border-radius:5px; background:#e9edff; color:#5946d8; font-size:10px; font-weight:700; }
.semantic-proof-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin-top:12px; }.semantic-proof-grid div { min-width:0; padding:9px; border-radius:7px; background:#fff; }.semantic-proof-grid small,.semantic-proof-row small { display:block; margin-bottom:3px; color:#92929c; font-size:9px; }.semantic-proof-grid strong { display:block; overflow:hidden; color:#454550; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.source-discovery{margin:14px 20px;padding:14px;border:1px solid #f0d5a8;border-radius:10px;background:#fffaf2}.source-discovery.success{border-color:#bfe4cc;background:#f4fbf6}.source-discovery-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.source-discovery-title div strong{display:block;color:#714d14;font-size:12px}.source-discovery.success .source-discovery-title div strong{color:#23723f}.source-discovery-title div span{display:block;margin-top:3px;color:#999184;font-size:9px}.source-discovery-title>span{padding:3px 7px;border-radius:999px;background:#fff0d6;color:#9b6100;font-size:9px}.source-discovery.success .source-discovery-title>span{background:#dff4e6;color:#257342}.source-discovery-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-top:12px}.source-discovery-grid div{min-width:0;padding:8px;border-radius:7px;background:rgba(255,255,255,.78)}.source-discovery-grid small{display:block;color:#999184;font-size:8px}.source-discovery-grid strong{display:block;overflow:hidden;margin-top:3px;color:#55505a;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.source-discovery-evidence{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;color:#4f6f59;font-size:10px}.source-discovery-blocker{margin-top:10px;padding:10px;border-radius:7px;background:#fff}.source-discovery-blocker>strong{color:#a15d00;font-size:10px}.source-discovery-blocker p{margin:5px 0 0;color:#6d6253;font-size:10px;line-height:1.5}.source-discovery-blocker b{color:#8d5b0e}.source-discovery-blocker small{display:block;margin-top:7px;color:#999184;font-size:9px;word-break:break-all}.step-needs_context{background:#fff0d6!important;color:#9b6100!important}
.semantic-proof-row { margin-top:8px; color:#5e5e68; font-size:10px; }.semantic-proof-row code { white-space:normal; word-break:break-all; }.semantic-proof ul { margin:9px 0 0; padding-left:16px; color:#686873; font-size:10px; line-height:1.6; }.semantic-checks{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.semantic-checks span{padding:4px 7px;border-radius:6px;background:#fff0f0;color:#b33;font-size:10px}.semantic-checks span.passed{background:#eaf8ef;color:#247a43}
.technical-collapse { border-top: 1px solid #ededf0; border-bottom: 0; padding: 0 20px; }.technical-collapse :deep(.el-collapse-item__header){font-size:11px;color:#777780}.artifact-list article { margin-bottom: 10px; }.artifact-list strong { color: #55555d; font-size: 11px; }.artifact-list pre,.json-detail { max-height: 260px; overflow: auto; padding: 12px; border-radius: 8px; background: #17171b; color: #dddde3; font-size: 10px; white-space: pre-wrap; }.artifact-list p { color: #66666e; font-size: 12px; white-space: pre-wrap; }
.question-card { margin: 14px 0 20px 40px; padding: 16px; border: 1px solid #f0d5a8; border-radius: 10px; background: #fffaf2; }.question-card>strong { display: block; margin-bottom: 8px; color: #8d5b0e; font-size: 12px; }.question-card button { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border: 0; border-top: 1px solid #f3e5cb; background: transparent; color: #765723; font-size: 12px; cursor: pointer; text-align: left; }
.composer-shell { min-height: 0; flex-shrink: 0; padding: 12px 24px 14px; background: linear-gradient(180deg,rgba(255,255,255,.5),#fff 18%); }.composer-box { width: min(900px,100%); margin: 0 auto; overflow: hidden; border: 1px solid #d9d9de; border-radius: 12px; background: #fff; box-shadow: 0 5px 18px rgba(0,0,0,.055); transition: .2s; }.composer-box.focused { border-color: #8a72f8; box-shadow: 0 0 0 3px rgba(107,78,255,.09),0 8px 24px rgba(0,0,0,.06); }.composer-box textarea { width: 100%; min-height: 52px; max-height: 140px; box-sizing: border-box; resize: none; padding: 15px 16px 8px; border: 0; outline: 0; color: #2c2c32; font: 13px/1.6 inherit; }.composer-box textarea::placeholder { color: #aaaab0; }.composer-toolbar { display: flex; align-items: center; gap: 10px; padding: 5px 7px 7px 11px; }.settings-button { display: flex; align-items: center; gap: 6px; padding: 5px 7px; border: 0; border-radius: 6px; background: transparent; color: #777780; font-size: 11px; cursor: pointer; }.settings-button:hover { background: #f2f2f4; }.guard-hint { display: flex; align-items: center; gap: 4px; color: #aaaab0; font-size: 10px; }.send-button { width: 31px; height: 31px; display: grid; place-items: center; margin-left: auto; border: 0; border-radius: 8px; background: #6748ef; color: #fff; cursor: pointer; }.send-button:disabled { background: #d8d4e8; cursor: not-allowed; }.send-spinner { width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.45); border-top-color:#fff; border-radius:50%; animation:spin .8s linear infinite; }.composer-shell>p { margin: 7px 0 0; color: #aaaab0; font-size: 9px; text-align: center; }.run-settings>strong { display: block; margin-bottom: 10px; }.run-settings label { min-height: 44px; display: flex; align-items: center; justify-content: space-between; gap: 12px; border-top: 1px solid #ededf0; color: #55555d; font-size: 12px; }.run-settings label span small { display: block; margin-top: 2px; color: #aaaab0; font-size: 9px; }
@keyframes pulse{to{opacity:.25;transform:translateY(-2px)}}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:900px){.source-discovery-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.agent-workspace{grid-template-columns:1fr}.conversation-rail{display:none}.result-metrics{grid-template-columns:repeat(2,1fr)}.result-metrics div:nth-child(2){border-right:0}.prompt-grid{grid-template-columns:1fr}.chat-header{padding:0 16px}.composer-shell{padding-left:12px;padding-right:12px}.message-list{width:calc(100% - 24px)}.welcome-panel{width:calc(100% - 24px)}}
.mode-control { display: flex; align-items: center; gap: 8px; color: #55555d; font-size: 11px; font-weight: 600; }
.execution-warning { padding: 4px 7px; border: 1px solid #ffd7a8; border-radius: 6px; background: #fff7e8; color: #a85b00; font-size: 10px; }
.response-errors { margin-top: 12px; padding: 11px 12px; border: 1px solid #ffd2d2; border-radius: 9px; background: #fff7f7; color: #8f2f2f; }
.response-errors strong, .next-actions strong { display: block; margin-bottom: 6px; font-size: 12px; }
.response-errors p { margin: 3px 0; font-size: 11px; line-height: 1.5; word-break: break-word; }
.next-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 12px; }
.next-actions strong { width: 100%; color: #55555d; }
.next-actions button { padding: 6px 9px; border: 1px solid #dedee6; border-radius: 7px; background: #fff; color: #5c45c7; font-size: 11px; cursor: pointer; }
.next-actions button:hover { border-color: #8a72f8; background: #f8f6ff; }
.custom-input-hint { width: 100%; color: #777780; font-size: 11px; line-height: 1.4; }

.publish-approval { margin-top: 14px; padding: 14px; border: 1px solid #ead9a6; border-radius: 10px; background: #fffaf0; }
.publish-approval-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.publish-approval-head div { display: grid; gap: 2px; }
.publish-approval-head small { color: #9a6a00; font-size: 9px; font-weight: 700; letter-spacing: .08em; }
.publish-approval-head strong { color: #4a3a10; font-size: 13px; }
.publish-approval-head>span { max-width: 48%; overflow: hidden; color: #80631b; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.publish-approval>p { margin: 9px 0 0; color: #6b5a2d; font-size: 11px; line-height: 1.55; }
.publish-actions { display: flex; gap: 8px; margin-top: 12px; }
.publish-actions button { padding: 7px 12px; border-radius: 7px; font-size: 11px; font-weight: 600; cursor: pointer; }
.publish-actions button:disabled { opacity: .55; cursor: wait; }
.approve-button { border: 1px solid #6748ef; background: #6748ef; color: #fff; }
.reject-button { border: 1px solid #d7caa5; background: #fff; color: #775f20; }
.publish-approval .publish-feedback { color: #4f4380; font-weight: 600; }

.policy-stack { gap: 10px; }
.boundary-card { padding: 12px; border: 1px solid rgba(255,255,255,.12); border-radius: 12px; background: rgba(255,255,255,.06); }
.boundary-card .rail-label { margin-bottom: 8px; display: block; }
.boundary-card ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.boundary-card li { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 8px; border-radius: 8px; background: rgba(255,255,255,.06); }
.boundary-card li strong { color: #f5f4ff; font-size: 11px; }
.boundary-card li small { color: #b9b4df; font-size: 10px; white-space: nowrap; }
.boundary-card li.allow small { color: #83e0ad; }
.boundary-card li.confirm small { color: #ffd27b; }
.boundary-card li.manual small { color: #ff9f9f; }
.knowledge-card p { margin: 0; color: #d6d2f4; font-size: 11px; line-height: 1.55; }
</style>
