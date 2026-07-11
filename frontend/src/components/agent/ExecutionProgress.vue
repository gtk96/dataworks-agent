<template>
  <div class="execution-progress">
    <div class="progress-line">
      <span>{{ status.completed_steps }}/{{ status.total_steps }}</span>
      <el-progress :percentage="progressPercentage" :status="progressStatus" :stroke-width="10" />
    </div>

    <div class="step-list">
      <div v-for="step in steps" :key="step.step_id" class="step-item" :class="step.status">
        <el-icon class="step-icon">
          <Check v-if="step.status === 'completed'" />
          <Close v-else-if="step.status === 'failed'" />
          <Loading v-else-if="step.status === 'running'" />
          <Clock v-else />
        </el-icon>
        <div class="step-copy">
          <strong>{{ step.title || step.tool }}</strong>
          <small>{{ step.phase || step.tool }} · {{ statusLabel(step.status) }}</small>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Check, Clock, Close, Loading } from '@element-plus/icons-vue'

interface StepStatus {
  step_id: string
  tool: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  title?: string
  phase?: string
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
  if (props.status.total_steps > 0 && props.status.completed_steps === props.status.total_steps) return 'success'
  return undefined
})

const steps = computed(() => Object.values(props.status.steps))

function statusLabel(status: StepStatus['status']) {
  const map: Record<StepStatus['status'], string> = {
    pending: '等待中',
    running: '规划中',
    completed: '已完成',
    failed: '失败',
  }
  return map[status]
}
</script>

<style scoped>
.execution-progress {
  padding: 4px 0 0;
}

.progress-line {
  display: grid;
  grid-template-columns: 44px 1fr;
  gap: 10px;
  align-items: center;
  color: #667085;
  font-weight: 700;
}

.step-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.step-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px;
  border-radius: 14px;
  background: #f8faff;
  border: 1px solid rgba(98, 128, 210, 0.1);
}

.step-icon {
  margin-top: 2px;
  color: #98a2b3;
}

.step-copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.step-copy strong {
  color: #1f2a44;
  font-size: 13px;
}

.step-copy small {
  color: #98a2b3;
}

.step-item.completed .step-icon,
.step-item.completed small {
  color: #16a34a;
}

.step-item.failed .step-icon,
.step-item.failed small {
  color: #ef4444;
}

.step-item.running .step-icon,
.step-item.running small {
  color: #d97706;
}
</style>
