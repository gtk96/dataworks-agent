<template>
  <div>
    <el-page-header @back="$router.push('/tasks')" :content="'任务 ' + task?.task_id" />
    <div style="margin-top: 20px" v-if="task">
      <!-- 基本信息 -->
      <el-descriptions border :column="3">
        <el-descriptions-item label="状态">
          <el-tag :type="statusType(task.status)">{{ statusLabel(task.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="任务 ID">{{ task.task_id }}</el-descriptions-item>
        <el-descriptions-item label="节点类型">{{ task.node_type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="源表">{{ task.source_table }}</el-descriptions-item>
        <el-descriptions-item label="目标表">{{ task.target_table }}</el-descriptions-item>
        <el-descriptions-item label="层">{{ task.target_layer }}</el-descriptions-item>
        <el-descriptions-item label="域">{{ task.domain || '-' }}</el-descriptions-item>
        <el-descriptions-item label="实体">{{ task.entity || '-' }}</el-descriptions-item>
        <el-descriptions-item label="更新方式">{{ task.update_method || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建 IP">{{ task.created_by_ip || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ task.created_at }}</el-descriptions-item>
        <el-descriptions-item label="耗时">{{ task.duration_seconds ? task.duration_seconds.toFixed(1) + 's' : '-' }}</el-descriptions-item>
        <el-descriptions-item label="节点 UUID" :span="2" v-if="task.node_uuid">
          <el-tag type="info" size="small">{{ task.node_uuid }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="节点名称" v-if="task.node_name">{{ task.node_name }}</el-descriptions-item>
      </el-descriptions>

      <!-- 错误信息 -->
      <el-alert v-if="task.error_message" type="error" :closable="false" style="margin-top:16px"
        :title="'错误信息'" :description="task.error_message" show-icon />

      <!-- SSE 实时进度 -->
      <el-card header="执行进度" style="margin-top: 20px" v-if="streaming">
        <el-steps :active="progressStep" align-center>
          <el-step title="DDL 生成" />
          <el-step title="建表执行" />
          <el-step title="词根校验" />
          <el-step title="DML 写入" />
          <el-step title="调度配置" />
          <el-step title="测试验证" />
        </el-steps>
        <el-progress :percentage="progressPct" style="margin-top: 20px" />
      </el-card>

      <!-- DDL DEV -->
      <el-card header="DDL (DEV)" style="margin-top: 20px" v-if="task.ddl_dev">
        <pre style="background:#f5f5f5;padding:12px;overflow-x:auto;font-size:12px;max-height:400px">{{ task.ddl_dev }}</pre>
      </el-card>

      <!-- DDL PROD -->
      <el-card header="DDL (PROD)" style="margin-top: 10px" v-if="task.ddl_prod">
        <pre style="background:#f5f5f5;padding:12px;overflow-x:auto;font-size:12px;max-height:400px">{{ task.ddl_prod }}</pre>
      </el-card>

      <!-- DML -->
      <el-card header="DML" style="margin-top: 10px" v-if="task.dml">
        <pre style="background:#f5f5f5;padding:12px;overflow-x:auto;font-size:12px;max-height:300px">{{ task.dml }}</pre>
      </el-card>

      <!-- 步骤日志 -->
      <el-card header="步骤日志" style="margin-top: 10px" v-if="stepLogs.length">
        <el-table :data="stepLogs" size="small" border>
          <el-table-column prop="step_name" label="步骤" width="120" />
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'info'" size="small">
                {{ row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="intent_operation" label="操作" width="120" />
          <el-table-column prop="intent_target" label="目标" width="150" />
          <el-table-column prop="error" label="错误" />
        </el-table>
        <el-button style="margin-top:12px" size="small" @click="loadFullLogs" :loading="loadingLogs">
          查看完整日志 (/api/logs)
        </el-button>
        <pre v-if="fullLogs" style="background:#f5f5f5;padding:12px;margin-top:12px;overflow-x:auto;font-size:12px;max-height:400px">{{ fullLogs }}</pre>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '@/utils/request'
import { createSSEStream, type SSEEvent } from '@/utils/sse'

const route = useRoute()
const taskId = route.params.id as string
const task = ref<any>(null)
const stepLogs = ref<any[]>([])
const streaming = ref(false)
const progressStep = ref(0)
const progressPct = ref(0)
const fullLogs = ref<string>('')
const loadingLogs = ref(false)
let controller: AbortController | null = null

async function loadFullLogs() {
  loadingLogs.value = true
  try {
    const r = await request<{ logs: any[] }>(`/api/logs?task_id=${taskId}&limit=200`)
    fullLogs.value = (r.logs || []).map((l: any) => `[${l.created_at || ''}] ${l.step_name || ''} ${l.status || ''} ${l.error || ''}`).join('\n')
  } catch (e: any) {
    fullLogs.value = `加载失败: ${e.message}`
  }
  loadingLogs.value = false
}

function statusType(s: string) {
  const map: Record<string, string> = {
    completed: 'success', failed: 'danger', running: 'primary',
    cancelled: 'info', suspended: 'warning',
  }
  return map[s] || 'warning'
}

function statusLabel(s: string) {
  // 中文 label 让 TaskList/TaskDetail 状态显示一致；未知值兜底原值
  const map: Record<string, string> = {
    pending: '待启动', running: '运行中',
    ddl_gen: 'DDL 生成', table_cre: '建表执行', root_check: '词根校验',
    dml_write: 'DML 写入', sched_cfg: '调度配置', testing: '测试验证',
    completed: '已完成', failed: '失败', cancelled: '已取消', suspended: '已挂起',
  }
  return map[s] || s
}

// 6 个执行步骤的状态 → step 索引；终态不映射（保留 lastProgress）
const STEP_MAP: Record<string, number> = {
  ddl_gen: 1, table_cre: 2, root_check: 3, dml_write: 4, sched_cfg: 5, testing: 6,
  pending: 0, running: 1, completed: 6,
}

function isTerminalStatus(s: string) {
  return s === 'completed' || s === 'failed' || s === 'cancelled' || s === 'suspended'
}

onMounted(async () => {
  try {
    const r = await request<{ task: any; step_logs?: any[] }>(`/api/modeling/tasks/${taskId}`)
    task.value = r.task
    stepLogs.value = r.step_logs || []
    // 初始进度：后端 status 可能就是中间态，先把进度对齐
    const init = STEP_MAP[r.task.status]
    if (init !== undefined) {
      progressStep.value = init
      progressPct.value = Math.min(100, (init / 6) * 100)
    }
    if (!isTerminalStatus(r.task.status)) {
      streaming.value = true
      controller = createSSEStream(
        `/api/modeling/tasks/${taskId}/stream`,
        (evt: SSEEvent) => {
          // 终态事件（failed/cancelled/suspended）保留最后进度，不跳回 0%
          const next = STEP_MAP[evt.status]
          if (next !== undefined) {
            progressStep.value = next
            progressPct.value = evt.status === 'completed'
              ? 100
              : Math.min(100, (next / 6) * 100)
          }
          if (evt.data?.steps) task.value.steps = evt.data.steps
          if (evt.data?.ddl_dev) task.value.ddl_dev = evt.data.ddl_dev
          if (evt.data?.dml) task.value.dml = evt.data.dml
        },
        (err) => { console.error('SSE 错误:', err); streaming.value = false },
      )
    }
  } catch {}
})

onUnmounted(() => { controller?.abort() })
</script>
