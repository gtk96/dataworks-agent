<template>
  <div v-loading="!loaded" element-loading-text="仪表盘加载中...">
    <!-- Agent 对话入口 -->
    <el-drawer v-model="showChat" title="数仓助手" size="420px" :with-header="true">
      <AgentChat />
    </el-drawer>
    <el-button class="chat-fab" circle @click="showChat = true">
      <el-icon :size="24"><ChatDotRound /></el-icon>
    </el-button>
    <el-alert
      v-if="loadError && loaded"
      type="error"
      :closable="false"
      title="仪表盘数据加载失败"
      description="已展示最近一次成功缓存的数据；30 秒后将自动重试。"
      style="margin-bottom: 16px"
    />
    <el-row :gutter="20" style="margin-bottom: 20px">
      <el-col :span="4">
        <el-statistic title="总任务" :value="d.total_tasks" />
      </el-col>
      <el-col :span="4">
        <el-statistic title="已完成" :value="d.completed" />
      </el-col>
      <el-col :span="4">
        <el-statistic title="失败" :value="d.failed" />
      </el-col>
      <el-col :span="4">
        <el-statistic title="待执行" :value="d.pending" />
      </el-col>
      <el-col :span="4">
        <el-statistic title="成功率" :value="d.success_rate ?? 0" :precision="1" suffix="%" />
      </el-col>
      <el-col :span="4">
        <el-statistic title="平均耗时" :value="d.avg_duration_seconds ?? 0" :precision="1" suffix="s" />
      </el-col>
    </el-row>

    <el-row :gutter="20">
      <el-col :span="12">
        <el-card header="任务状态分布">
          <el-row :gutter="12">
            <el-col :span="6" style="text-align:center">
              <div style="font-size:28px;color:#409EFF">{{ d.running }}</div>
              <div style="font-size:12px;color:#999">运行中</div>
            </el-col>
            <el-col :span="6" style="text-align:center">
              <div style="font-size:28px;color:#909399">{{ d.pending }}</div>
              <div style="font-size:12px;color:#999">等待中</div>
            </el-col>
            <el-col :span="6" style="text-align:center">
              <div style="font-size:28px;color:#67C23A">{{ d.completed }}</div>
              <div style="font-size:12px;color:#999">已完成</div>
            </el-col>
            <el-col :span="6" style="text-align:center">
              <div style="font-size:28px;color:#F56C6C">{{ d.failed }}</div>
              <div style="font-size:12px;color:#999">失败</div>
            </el-col>
          </el-row>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card header="按任务类型">
          <div v-for="item in typeRows" :key="item.key" style="margin: 10px 0">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
              <el-tag :type="item.tagType" size="small">{{ item.label }}</el-tag>
              <span style="font-size:12px;color:#666">共 {{ item.total }} · 成功 {{ item.completed }} · 失败 {{ item.failed }}</span>
            </div>
            <el-progress
              :percentage="item.percent"
              :stroke-width="16"
              :text-inside="true"
              :color="item.color"
            >
              {{ item.total }}
            </el-progress>
          </div>
          <div v-if="!typeRows.length" style="color:#999;text-align:center;padding:20px">
            暂无任务记录
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top:20px">
      <el-col :span="24">
        <el-card header="按数仓分层（建模向导）">
          <el-row :gutter="16">
            <el-col v-for="(v, k) in d.layer_breakdown" :key="k" :span="4" style="text-align:center">
              <div style="font-size:22px;font-weight:600">{{ v }}</div>
              <div style="font-size:12px;color:#999">{{ k }}</div>
            </el-col>
          </el-row>
          <div v-if="!Object.keys(d.layer_breakdown).length" style="color:#999;text-align:center;padding:12px">
            暂无分层统计
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card header="快捷操作" style="margin-top: 20px">
      <el-button type="primary" size="large" @click="$router.push('/tasks/create')">新建建模任务</el-button>
      <el-button size="large" @click="$router.push('/di')">数据集成</el-button>
      <el-button size="large" @click="$router.push('/tasks')">查看任务列表</el-button>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound } from '@element-plus/icons-vue'
import { request } from '@/utils/request'
import AgentChat from '@/components/agent/AgentChat.vue'

const showChat = ref(false)

type TypeBucket = { total: number; completed: number; failed: number; running?: number; pending?: number }

function normalizeTypeBucket(raw: unknown): TypeBucket {
  if (typeof raw === 'number') {
    return { total: raw, completed: raw, failed: 0 }
  }
  if (raw && typeof raw === 'object') {
    const o = raw as Record<string, number>
    return {
      total: o.total ?? 0,
      completed: o.completed ?? 0,
      failed: o.failed ?? 0,
      running: o.running,
      pending: o.pending,
    }
  }
  return { total: 0, completed: 0, failed: 0 }
}

function normalizeTypeBreakdown(raw: Record<string, unknown> | undefined): Record<string, TypeBucket> {
  // R3: 直接以后端返回的 type_breakdown 键为准（后端 NODE_TYPE_LABELS 为唯一来源），
  // 避免前后端各自硬编码节点类型列表、导致新增类型时被静默漏显示
  const out: Record<string, TypeBucket> = {}
  for (const key of Object.keys(raw ?? {})) {
    out[key] = normalizeTypeBucket(raw?.[key])
  }
  return out
}

const d = ref({
  total_tasks: 0, completed: 0, failed: 0, pending: 0, running: 0,
  success_rate: 0, avg_duration_seconds: 0,
  layer_breakdown: {} as Record<string, number>,
  type_breakdown: {} as Record<string, TypeBucket>,
})
const loaded = ref(false)
const loadError = ref(false)

const TYPE_META: Record<string, { label: string; tagType: 'success' | 'warning' | 'primary'; color: string }> = {
  holo: { label: 'Holo SQL', tagType: 'warning', color: '#E6A23C' },
  di: { label: '数据集成 DI', tagType: 'success', color: '#67C23A' },
  'odps-sql': { label: 'MaxCompute SQL', tagType: 'primary', color: '#409EFF' },
}

const typeRows = computed(() => {
  const breakdown = normalizeTypeBreakdown(d.value.type_breakdown as Record<string, unknown>)
  const totalAll = Object.values(breakdown).reduce((sum, b) => sum + b.total, 0)
  // R3: 直接遍历后端返回的 type_breakdown 键（后端 NODE_TYPE_LABELS 为唯一来源），
  // 新增节点类型时自动显示；未知类型回退到原始 key，避免 TYPE_META 缺项崩溃
  return Object.keys(breakdown)
    .map((key) => {
      const bucket = breakdown[key]
      const meta = TYPE_META[key] ?? { label: key, tagType: 'primary' as const, color: '#909399' }
      return {
        key,
        label: meta.label,
        tagType: meta.tagType,
        color: meta.color,
        total: bucket.total,
        completed: bucket.completed,
        failed: bucket.failed,
        percent: totalAll ? Math.round((bucket.total / totalAll) * 100) : 0,
      }
    })
    .filter((row) => row.total > 0)
})

// ── WebSocket 实时（v10：事件驱动推送 + 30s HTTP 兜底） ──
let _ws: WebSocket | null = null
let _wsTimer: ReturnType<typeof setInterval> | null = null

function _applyRaw(raw: Record<string, unknown>) {
  d.value = {
    ...d.value,
    ...raw,
    type_breakdown: normalizeTypeBreakdown(raw.type_breakdown as Record<string, unknown>),
  } as typeof d.value
  loadError.value = false
  loaded.value = true
}

function _loadOnce() {
  return request<Record<string, unknown>>('/api/monitor/dashboard')
    .then(_applyRaw)
    .catch((e: unknown) => {
      loadError.value = true
      loaded.value = true
      // 首次加载失败才弹错误；后续轮询静默（已展示旧数据）
      if (!d.value.total_tasks) {
        ElMessage.error(`加载仪表盘失败：${(e as Error)?.message ?? '网络异常'}，请稍后重试`)
      }
      console.warn('仪表盘加载失败:', e)
    })
}

function _connectWs() {
  // R2: 先关掉旧连接再建新，避免 CONNECTING 态被定时器重复建连导致泄漏 / 错误置空引用
  if (_ws) {
    _ws.onclose = null
    _ws.onerror = null
    try { _ws.close() } catch { /* ignore */ }
    _ws = null
  }
  try {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${protocol}//${location.host}/api/monitor/ws/tasks`)
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg?.type === 'task_status_changed' && msg.status) {
          // 单事件不足以刷新整张 dashboard（聚合数字需 SQL），
          // 这里只触发一次轻量级 HTTP 拉取，比 30s 轮询响应快得多
          _loadOnce()
        }
      } catch {
        /* ignore non-JSON frames (e.g. hello) */
      }
    }
    // 仅当仍是当前 socket 时才置空，避免旧 socket 的回调误清空新引用（R2）
    ws.onclose = () => { if (_ws === ws) _ws = null }
    ws.onerror = () => { if (_ws === ws) _ws = null }
    _ws = ws
  } catch { /* ignore */ }
}

onMounted(async () => {
  await _loadOnce()

  // WS 事件驱动刷新；30s HTTP 仅作兜底（防 WS 漏连/事件漏发）
  _connectWs()
  _wsTimer = setInterval(() => {
    // R2: 仅当连接不存在或已关闭才重连；CONNECTING/CLOSING 不重连，避免重复建连泄漏
    if (!_ws || _ws.readyState === WebSocket.CLOSED) {
      _connectWs()
    }
    _loadOnce()
  }, 30000)
})

onUnmounted(() => {
  if (_wsTimer) clearInterval(_wsTimer)
  if (_ws) { _ws.onclose = null; _ws.close(); _ws = null }
})
</script>

<style scoped>
.chat-fab {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 56px;
  height: 56px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  z-index: 1000;
}
</style>
