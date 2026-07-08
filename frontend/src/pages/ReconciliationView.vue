<template>
  <div>
    <el-alert type="info" title="协调处置" description="进程崩溃后未确认的操作，需人工确认远程状态" show-icon style="margin-bottom: 20px" />
    <el-table :data="tasks" @load="load">
      <el-table-column prop="task_id" label="任务 ID" width="180" />
      <el-table-column prop="step_name" label="步骤" width="120" />
      <el-table-column prop="operation" label="操作" width="150" />
      <el-table-column prop="target" label="目标" />
      <el-table-column label="处置" width="280">
        <template #default="{ row }">
          <el-button size="small" type="success" @click="dispose(row.id, 'confirm_success')">确认成功</el-button>
          <el-button size="small" type="danger" @click="dispose(row.id, 'confirm_failed')">确认失败</el-button>
          <el-button size="small" @click="dispose(row.id, 'retry')">重试</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="!tasks.length" style="text-align:center;padding:40px;color:#999">暂无待协调任务</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const tasks = ref<any[]>([])

async function load() {
  const r = await request<{ tasks: any[] }>('/api/reconciliation/tasks')
  tasks.value = r.tasks
}

async function dispose(taskId: string, action: string) {
  try {
    await request('/api/reconciliation/dispose', { method: 'POST', body: { task_id: taskId, action } })
    ElMessage.success('处置完成')
    load()
  } catch (e: any) { ElMessage.error(e.message) }
}

onMounted(load)
</script>
