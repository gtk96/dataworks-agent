<template>
  <div>
    <el-row style="margin-bottom: 16px">
      <el-col :span="6">
        <el-select v-model="filter.status" placeholder="按状态筛选" clearable @change="onFilterChange">
          <el-option-group label="执行中">
            <el-option v-for="s in ['pending','running','ddl_gen','table_cre','root_check','dml_write','sched_cfg','testing']"
                       :key="s" :value="s" :label="statusLabel(s)" />
          </el-option-group>
          <el-option-group label="已结束">
            <el-option v-for="s in ['completed','failed','cancelled','suspended']"
                       :key="s" :value="s" :label="statusLabel(s)" />
          </el-option-group>
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-select v-model="filter.layer" placeholder="按层筛选" clearable @change="onFilterChange">
          <el-option v-for="l in ['ODS','DWD','DWS','DMR','DIM']" :key="l" :value="l" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-select v-model="filter.nodeType" placeholder="按任务类型" clearable @change="onFilterChange">
          <el-option value="holo" label="Holo SQL" />
          <el-option value="di" label="数据集成 DI" />
          <el-option value="odps-sql" label="MaxCompute SQL" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-select v-model="filter.scope" @change="onFilterChange" style="width:100%">
          <el-option value="mine" label="我的任务" />
          <el-option value="all" label="全部任务" />
        </el-select>
      </el-col>
      <el-col :span="6" style="text-align: right">
        <el-button type="primary" @click="$router.push('/tasks/create')">+ 新建任务</el-button>
      </el-col>
    </el-row>

    <el-table :data="tasks" style="width: 100%" :row-class-name="rowClass">
      <el-table-column prop="task_id" label="任务 ID" width="180" />
      <el-table-column prop="target_table" label="目标表" min-width="180" />
      <el-table-column prop="target_layer" label="分层" width="70" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag v-if="displayNodeType(row)==='holo'" type="warning" size="small">Holo</el-tag>
          <el-tag v-else-if="displayNodeType(row)==='odps-sql'" type="primary" size="small">MC SQL</el-tag>
          <el-tag v-else-if="displayNodeType(row)==='di'" type="success" size="small">DI</el-tag>
          <span v-else style="color:#999">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="80" align="right">
        <template #default="{ row }">
          <span v-if="row.duration_seconds">{{ row.duration_seconds.toFixed(1) }}s</span>
          <span v-else style="color:#999">-</span>
        </template>
      </el-table-column>
      <el-table-column v-if="filter.scope==='all'" prop="created_by_ip" label="创建 IP" width="120" />
      <el-table-column prop="created_at" label="创建时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="完成时间" width="170">
        <template #default="{ row }">
          <span v-if="row.updated_at && row.status !== 'pending'">{{ formatTime(row.updated_at) }}</span>
          <span v-else style="color:#999">-</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/tasks/${row.task_id}`)">详情</el-button>
          <el-button v-if="row.status==='failed'||row.status==='cancelled'" size="small" type="warning" @click="retryTask(row.task_id)">重试</el-button>
          <!-- 取消：覆盖 pending/running + 6 个中间态；终态和 SUSPENDED 不允许取消 -->
          <el-button v-if="isCancellable(row.status)" size="small" type="info" @click="cancelTask(row.task_id)">取消</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      style="margin-top:16px;justify-content:flex-end"
      layout="total, sizes, prev, pager, next"
      :total="total"
      :page-size="pageSize"
      :page-sizes="[10, 20, 50, 100]"
      :current-page="currentPage"
      @current-change="onPageChange"
      @size-change="onSizeChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const tasks = ref<any[]>([])
const filter = ref({ status: '', layer: '', nodeType: '', scope: 'mine' })
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

async function load() {
  const params = new URLSearchParams()
  if (filter.value.status) params.set('status', filter.value.status)
  if (filter.value.layer) params.set('layer', filter.value.layer)
  if (filter.value.nodeType) params.set('node_type', filter.value.nodeType)
  params.set('scope', filter.value.scope)
  params.set('page', String(currentPage.value))
  params.set('page_size', String(pageSize.value))
  const r = await request<{ tasks: any[]; total: number }>(`/api/modeling/tasks?${params}`)
  tasks.value = r.tasks
  total.value = r.total || 0
}

function onFilterChange() {
  currentPage.value = 1
  load()
}

function onPageChange(page: number) {
  currentPage.value = page
  load()
}
function onSizeChange(size: number) {
  pageSize.value = size
  currentPage.value = 1
  load()
}

async function retryTask(taskId: string) {
  try {
    await request(`/api/modeling/tasks/${taskId}/retry`, { method: 'POST' })
    ElMessage.success('重试任务已创建')
    load()
  } catch (e: any) {
    ElMessage.error(`重试失败: ${e.message}`)
  }
}

async function cancelTask(taskId: string) {
  try {
    await request(`/api/modeling/tasks/${taskId}/cancel`, { method: 'POST' })
    ElMessage.success('任务已取消')
    load()
  } catch (e: any) {
    ElMessage.error(`取消失败: ${e.message}`)
  }
}

// T7: 后端 list_tasks 已算好 node_type，前端直接采用，避免规则漂移产生不一致。
function displayNodeType(row: { node_type?: string }) {
  return (row.node_type || '').trim().toLowerCase() || 'odps-sql'
}

function statusType(s: string) {
  const map: Record<string, string> = {
    completed: 'success', failed: 'danger', running: 'primary',
    cancelled: 'info', suspended: 'warning',
  }
  return map[s] || 'warning'
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    pending: '待启动', running: '运行中',
    ddl_gen: 'DDL 生成', table_cre: '建表执行', root_check: '词根校验',
    dml_write: 'DML 写入', sched_cfg: '调度配置', testing: '测试验证',
    completed: '已完成', failed: '失败', cancelled: '已取消', suspended: '已挂起',
  }
  return map[s] || s
}

const IN_FLIGHT_STATUSES = new Set([
  'pending', 'running', 'ddl_gen', 'table_cre', 'root_check',
  'dml_write', 'sched_cfg', 'testing',
])
function isCancellable(s: string) {
  return IN_FLIGHT_STATUSES.has(s)
}
function rowClass({ row }: { row: any }) {
  return row.status === 'failed' ? 'error-row' : ''
}
function formatTime(t: string) {
  if (!t) return '-'
  const d = new Date(t)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

onMounted(load)
</script>

<style scoped>
:deep(.error-row) { background: #fef0f0; }
</style>
