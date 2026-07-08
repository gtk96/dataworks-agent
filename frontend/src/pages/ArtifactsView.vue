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
          <el-button size="small" type="primary" link @click="viewDetail(row.id)">详情</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const router = useRouter()
const filter = ref({ table_name: '', layer: '' })
const artifacts = ref<any[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

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

function viewDetail(id: number) {
  // 占位：后续可加详情页
  ElMessage.info(`产物 ID: ${id}，完整 DDL 可在弹窗查看`)
}

function onPageChange(page: number) {
  currentPage.value = page
  load()
}

onMounted(load)
</script>
