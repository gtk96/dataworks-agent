<template>
  <div class="execution-progress">
    <el-progress 
      :percentage="progressPercentage"
      :status="progressStatus"
    />
    
    <div class="step-list">
      <div 
        v-for="step in steps"
        :key="step.step_id"
        class="step-item"
        :class="step.status"
      >
        <el-icon>
          <Check v-if="step.status === 'completed'" />
          <Close v-if="step.status === 'failed'" />
          <Loading v-if="step.status === 'running'" />
        </el-icon>
        <span class="step-name">{{ step.tool }}</span>
        <span class="step-status">{{ step.status }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, Close, Loading } from '@element-plus/icons-vue'

interface StepStatus {
  step_id: string
  tool: string
  status: 'pending' | 'running' | 'completed' | 'failed'
}

const props = defineProps<{
  status: {
    total_steps: number
    completed_steps: number
    failed_steps: number
    steps: Record<string, StepStatus>
  }
}>()

const progressPercentage = computed(() => {
  if (props.status.total_steps === 0) return 0
  return Math.round((props.status.completed_steps / props.status.total_steps) * 100)
})

const progressStatus = computed(() => {
  if (props.status.failed_steps > 0) return 'exception'
  if (props.status.completed_steps === props.status.total_steps) return 'success'
  return undefined
})

const steps = computed(() => {
  return Object.values(props.status.steps)
})
</script>

<style scoped>
.execution-progress {
  padding: 12px 0;
}

.step-list {
  margin-top: 16px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid #f0f0f0;
}

.step-item:last-child {
  border-bottom: none;
}

.step-name {
  flex: 1;
}

.step-status {
  font-size: 12px;
  color: #999;
}

.step-item.completed .step-status {
  color: #67c23a;
}

.step-item.failed .step-status {
  color: #f56c6c;
}

.step-item.running .step-status {
  color: #e6a23c;
}
</style>