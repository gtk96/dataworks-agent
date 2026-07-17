<template>
  <div class="progress-tracker">
    <div class="tracker-header">
      <h3>📊 建模进度</h3>
      <span class="progress-percent">{{ percent }}%</span>
    </div>

    <div class="progress-bar-container">
      <div class="progress-bar" :style="{ width: percent + '%' }"></div>
    </div>

    <div class="steps-list">
      <div
        v-for="(step, index) in steps"
        :key="index"
        class="step-item"
        :class="step.status"
      >
        <div class="step-icon">
          <svg v-if="step.status === 'completed'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
          <svg v-else-if="step.status === 'running'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10" stroke-dasharray="31.4" stroke-dashoffset="10">
              <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/>
            </circle>
          </svg>
          <div v-else class="step-circle"></div>
        </div>
        <div class="step-content">
          <strong class="step-name">{{ step.name }}</strong>
          <span class="step-detail">{{ step.detail }}</span>
        </div>
        <div class="step-status">
          <span v-if="step.status === 'completed'" class="badge success">完成</span>
          <span v-else-if="step.status === 'running'" class="badge running">进行中</span>
          <span v-else class="badge pending">待执行</span>
        </div>
      </div>
    </div>

    <div v-if="nextActions && nextActions.length > 0" class="next-actions">
      <h4>下一步建议</h4>
      <div class="action-chips">
        <button
          v-for="action in nextActions"
          :key="action.id"
          class="action-chip"
          @click="$emit('action', action.id)"
        >
          {{ action.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Step {
  name: string
  detail: string
  status: 'pending' | 'running' | 'completed'
}

interface NextAction {
  id: string
  label: string
}

interface Props {
  steps: Step[]
  nextActions?: NextAction[]
}

const props = withDefaults(defineProps<Props>(), {
  nextActions: () => [],
})

const emit = defineEmits<{
  action: [id: string]
}>()

const completedCount = computed(() => props.steps.filter(s => s.status === 'completed').length)
const totalCount = computed(() => props.steps.length)
const percent = computed(() => totalCount.value > 0 ? Math.round((completedCount.value / totalCount.value) * 100) : 0)
</script>

<style scoped>
.progress-tracker {
  padding: 20px;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  background: var(--color-bg-secondary);
}

.tracker-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.tracker-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.progress-percent {
  font-size: 14px;
  font-weight: 700;
  color: #6366F1;
}

.progress-bar-container {
  height: 6px;
  background: var(--color-bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 20px;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #6366F1, #8B5CF6);
  border-radius: 3px;
  transition: width 0.5s ease;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--color-bg-tertiary);
  transition: all 0.2s;
}

.step-item.completed {
  background: rgba(34, 197, 94, 0.08);
  border: 1px solid rgba(34, 197, 94, 0.2);
}

.step-item.running {
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.step-icon {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
}

.step-icon svg {
  width: 20px;
  height: 20px;
}

.step-item.completed .step-icon svg {
  color: #22C55E;
}

.step-item.running .step-icon svg {
  color: #6366F1;
}

.step-circle {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-text-tertiary);
}

.step-item.running .step-circle {
  background: #6366F1;
  animation: pulse 1.5s ease-in-out infinite;
}

.step-content {
  flex: 1;
  min-width: 0;
}

.step-name {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.step-detail {
  display: block;
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 2px;
}

.step-status {
  flex-shrink: 0;
}

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.badge.success {
  background: rgba(34, 197, 94, 0.1);
  color: #22C55E;
}

.badge.running {
  background: rgba(99, 102, 241, 0.1);
  color: #6366F1;
}

.badge.pending {
  background: rgba(100, 116, 139, 0.1);
  color: var(--color-text-tertiary);
}

/* Next actions */
.next-actions {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--color-border-primary);
}

.next-actions h4 {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.action-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.action-chip {
  padding: 6px 12px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-tertiary);
  color: var(--color-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.action-chip:hover {
  border-color: #6366F1;
  color: #6366F1;
  background: rgba(99, 102, 241, 0.05);
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}
</style>
