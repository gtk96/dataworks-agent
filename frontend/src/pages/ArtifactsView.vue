<template>
  <div>
    <el-row :gutter="12" style="margin-bottom:16px">
      <el-col :span="8">
        <el-input v-model="filter.table_name" placeholder="按表名筛选" clearable @change="load" />
      </el-col>
      <el-col :span="6">
        <el-select v-model="filter.layer" placeholder="按层筛选" clearable style="width:100%" @change="load">
          <el-option value="ods" label="ODS" />
          <el-option value="dwd" label="DWD" />
          <el-option value="dws" label="DWS" />
          <el-option value="dim" label="DIM" />
          <el-option value="dmr" label="DMR" />
        </el-select>
      </el-col>
    </el-row>
    <el-table :data="artifacts" style="width:100%">
      <el-table-column prop="task_id" label="任务 ID" width="180" />
      <el-table-column prop="table_name" label="表名" min-width="180" />
      <el-table-column label="DDL (DEV)" width="80">
        <template #default="{ row }">
          <el-popover placement="left" width="600" trigger="click">
            <template #reference><el-button size="small" @click="fetchFullDdl(row)">查看</el-button></template>
            <pre style="font-size:12px;max-height:400px;overflow-y:auto">{{ row.ddl_dev_full || row.ddl_dev }}</pre>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="80">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="viewDetail(row)">详情</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="170" />
    </el-table>
    <el-pagination
      v-if="total > pageSize"
      style="margin-top:16px;justify-content:flex-end"
      layout="total, prev, pager, next"
      :total="total"
      :page-size="pageSize"
      :current-page="currentPage"
      @current-change="onPageChange"
    />

    <!-- 产物详情弹窗 -->
    <el-dialog v-model="detailVisible" :title="detailTable?.table_name || '产物详情'" width="720px">
      <template v-if="detailTable">
        <el-descriptions border :column="2" style="margin-bottom:16px">
          <el-descriptions-item label="任务 ID">{{ detailTable.task_id }}</el-descriptions-item>
          <el-descriptions-item label="表名">{{ detailTable.table_name }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detailTable.created_at }}</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="detailTable.error" type="error" :title="detailTable.error" :closable="false" style="margin-bottom:12px" />
        <template v-if="!detailTable.error">
          <div style="margin-bottom:8px;font-size:13px;font-weight:600">DDL (DEV)</div>
          <pre v-if="detailTable.ddl_dev" class="code-block" style="max-height:200px;margin-bottom:16px">{{ detailTable.ddl_dev }}</pre>
          <div v-else style="color:#999;font-size:12px;margin-bottom:16px">无</div>

          <div style="margin-bottom:8px;font-size:13px;font-weight:600">DDL (PROD)</div>
          <pre v-if="detailTable.ddl_prod" class="code-block" style="max-height:200px;margin-bottom:16px">{{ detailTable.ddl_prod }}</pre>
          <div v-else style="color:#999;font-size:12px;margin-bottom:16px">无</div>

          <div style="margin-bottom:8px;font-size:13px;font-weight:600">DML</div>
          <pre v-if="detailTable.dml" class="code-block" style="max-height:200px;margin-bottom:16px">{{ detailTable.dml }}</pre>
          <div v-else style="color:#999;font-size:12px;margin-bottom:16px">无</div>

          <div style="margin-bottom:8px;font-size:13px;font-weight:600">调度配置</div>
          <pre v-if="detailTable.schedule_config" class="code-block" style="max-height:200px;margin-bottom:16px">{{ detailTable.schedule_config }}</pre>
          <div v-else style="color:#999;font-size:12px;margin-bottom:16px">无</div>
        </template>
      </template>
      <template #footer>
        <el-button @click="detailVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const filter = ref({ table_name: '', layer: '' })
const artifacts = ref<any[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const detailVisible = ref(false)
const detailTable = ref<any>(null)

async function load() {
  const params = new URLSearchParams()
  if (filter.value.table_name) params.set('table_name', filter.value.table_name)
  if (filter.value.layer) params.set('layer', filter.value.layer)
  params.set('limit', String(pageSize.value))
  params.set('offset', String((currentPage.value - 1) * pageSize.value))
  const r = await request<{ artifacts: any[]; total: number }>(`/api/artifacts/ddl?${params}`)
  artifacts.value = r.artifacts
  total.value = r.total || 0
}

async function fetchFullDdl(row: any) {
  if (row.ddl_dev_full) return
  try {
    const r = await request<any>(`/api/artifacts/ddl/${row.id}`)
    row.ddl_dev_full = r.ddl_dev
  } catch {
    ElMessage.warning('获取完整 DDL 失败')
  }
}

async function viewDetail(row: any) {
  detailTable.value = { error: null, ddl_dev: '', ddl_prod: '', dml: '', schedule_config: '', ...row }
  detailVisible.value = true
  try {
    const r = await request<any>(`/api/artifacts/ddl/${row.id}`)
    // schedule_config_json is a JSON string; parse it for prettification
    let sched = ''
    if (r.schedule_config) {
      try { sched = JSON.stringify(JSON.parse(r.schedule_config), null, 2) } catch { sched = r.schedule_config }
    }
    detailTable.value = {
      ...r,
      schedule_config: sched,
      error: null,
    }
  } catch (e: any) {
    detailTable.value.error = e.message
  }
}

function onPageChange(page: number) {
  currentPage.value = page
  load()
}

onMounted(load)
</script>

<style scoped>
.code-block {
  background: #1e1e2e;
  border: 1px solid #313240;
  border-radius: 6px;
  padding: 10px 14px;
  font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #cdd6f4;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
  overflow-y: auto;
}
.code-block::-webkit-scrollbar {
  width: 6px;
}
.code-block::-webkit-scrollbar-thumb {
  background: #45475a;
  border-radius: 3px;
}
.code-block::-webkit-scrollbar-track {
  background: transparent;
}
</style>
