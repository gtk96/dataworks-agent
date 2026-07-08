<template>
  <div>
    <el-row :gutter="20">
      <el-col :span="12">
        <el-card header="可同步表（dev→prod）">
          <el-table :data="tables" @row-click="selectTable">
            <el-table-column prop="table_name" label="表名" />
            <el-table-column prop="layer" label="层" width="80" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button size="small" @click="doDiff(row.table_name)">对比</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card header="DDL 差异对比" v-if="diff">
          <div v-if="diff.has_changes">
            <el-alert type="warning" title="发现差异" :closable="false" />
            <pre style="background:#fff3e0;padding:8px;font-size:12px;max-height:300px;overflow-y:auto">{{ diff.alter_sql }}</pre>
            <el-button type="danger" @click="doSync">确认同步至生产</el-button>
          </div>
          <el-alert v-else type="success" title="dev 和 prod 已一致" :closable="false" />
        </el-card>
      </el-col>
    </el-row>

    <el-card header="同步历史" style="margin-top:20px">
      <el-table :data="history" size="small" max-height="400">
        <el-table-column prop="job_id" label="Job ID" width="180" />
        <el-table-column prop="source_table" label="源表" width="200" />
        <el-table-column prop="target_table" label="目标表" width="200" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'info'" size="small">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column prop="error" label="错误" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const tables = ref<any[]>([])
const diff = ref<any>(null)
const selectedTable = ref('')
const history = ref<any[]>([])

async function load() {
  const r = await request<{ tables: any[] }>('/api/sync/tables')
  tables.value = r.tables
  const h = await request<{ jobs: any[] }>('/api/sync/history')
  history.value = h.jobs || []
}

async function selectTable(row: any) {
  selectedTable.value = row.table_name
}

async function doDiff(name: string) {
  selectedTable.value = name
  diff.value = await request('/api/sync/diff', { method: 'POST', body: { table_name: name } })
}

async function doSync() {
  try {
    await request('/api/sync/execute', { method: 'POST', body: { table_name: selectedTable.value } })
    ElMessage.success('同步完成')
    diff.value = null
    load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

onMounted(load)
</script>
