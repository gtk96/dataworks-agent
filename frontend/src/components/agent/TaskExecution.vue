<template>
  <div class="task-execution">
    <div class="execution-header">
      <h4>任务执行</h4>
      <el-tag :type="statusType">{{ statusText }}</el-tag>
    </div>
    
    <ExecutionProgress 
      v-if="status"
      :status="status"
    />
    
    <div class="execution-actions">
      <el-button 
        v-if="status?.current_step"
        type="danger" 
        size="small"
        @click="$emit('cancel')"
      >
        取消执行
      </el-button>
      <el-button 
        v-if="status?.failed_steps > 0"
        type="warning" 
        size="small"
        @click="$emit('retry')"
      >
        重试失败步骤
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ExecutionProgress from './ExecutionProgress.vue'

interface ExecutionStatus {
  task_id: string
  current_step: string | null
  total_steps: number
  completed_steps: number
  failed_steps: number
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
  if (!props.status) return '等待中'
  if (props.status.failed_steps > 0) return '执行失败'
  if (props.status.current_step) return '执行中'
  return '已完成'
})
</script>

<style scoped>
.task-execution {
  padding: 16px;
  border: 1px solid #eee;
  border-radius: 8px;
}

.execution-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.execution-header h4 {
  margin: 0;
}

.execution-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}
</style>