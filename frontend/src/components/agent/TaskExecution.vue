<template>
  <div class="task-execution">
    <div class="execution-header">
      <div>
        <span class="caption">Task</span>
        <h4>{{ status?.task_id ?? '等待目标' }}</h4>
      </div>
      <el-tag :type="statusType" effect="light">{{ statusText }}</el-tag>
    </div>

    <ExecutionProgress v-if="status" :status="status" />

    <div class="execution-actions">
      <el-button v-if="status?.current_step" type="danger" plain size="small" @click="$emit('cancel')">
        停止等待
      </el-button>
      <el-button v-if="status && status.failed_steps > 0" type="warning" plain size="small" @click="$emit('retry')">
        让 Agent 诊断并重试
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ExecutionProgress from './ExecutionProgress.vue'

interface StepStatus {
  step_id: string
  tool: string
  status: 'pending' | 'running' | 'completed' | 'failed'
}

interface ExecutionStatus {
  task_id: string
  current_step: string | null
  total_steps: number
  completed_steps: number
  failed_steps: number
  steps: Record<string, StepStatus>
}

const props = defineProps<{
  status: ExecutionStatus | null
}>()

defineEmits<{
  cancel: []
  retry: []
}>()

const statusType = computed(() => {
  if (!props.status) return 'info'
  if (props.status.failed_steps > 0) return 'danger'
  if (props.status.current_step) return 'warning'
  return 'success'
})

const statusText = computed(() => {
  if (!props.status) return '等待目标'
  if (props.status.failed_steps > 0) return '需要处理'
  if (props.status.current_step) return '规划中'
  return '计划已生成'
})
</script>

<style scoped>
.task-execution {
  padding: 0;
}

.execution-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.caption {
  color: #94A3B8;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.1em;
}

.execution-header h4 {
  margin: 3px 0 0;
  color: #1E293B;
  font-size: 13px;
  line-height: 1.35;
  word-break: break-all;
}

.execution-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}
</style>
