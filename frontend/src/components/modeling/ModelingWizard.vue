<template>
  <div class="modeling-wizard">
    <div class="wizard-header">
      <h2>🚀 全链路建模向导</h2>
      <p>跟随向导完成从数据源到数仓的全链路建模</p>
    </div>

    <!-- Step indicators -->
    <div class="step-indicators">
      <div
        v-for="(step, index) in wizardSteps"
        :key="index"
        class="step-indicator"
        :class="{
          active: currentStep === index,
          completed: currentStep > index,
          upcoming: currentStep < index,
        }"
        @click="jumpToStep(index)"
      >
        <div class="step-number">{{ index + 1 }}</div>
        <span class="step-label">{{ step.label }}</span>
      </div>
    </div>

    <!-- Step content -->
    <div class="wizard-content">
      <!-- Step 1: Source selection -->
      <div v-if="currentStep === 0" class="step-panel">
        <DataSourceSelector @continue="onSourceSelected" />
      </div>

      <!-- Step 2: Table configuration -->
      <div v-else-if="currentStep === 1" class="step-panel">
        <h3>配置目标表</h3>
        <div class="form-group">
          <label>目标表名</label>
          <input
            v-model="config.targetTable"
            placeholder="例如: dwd_order_detail"
            class="form-input"
          />
        </div>
        <div class="form-group">
          <label>业务域</label>
          <input
            v-model="config.domain"
            placeholder="例如: trade"
            class="form-input"
          />
        </div>
        <div class="form-group">
          <label>调度周期</label>
          <select v-model="config.scheduleCycle" class="form-select">
            <option value="day">天级</option>
            <option value="hour">小时级</option>
          </select>
        </div>
      </div>

      <!-- Step 3: Review & Create -->
      <div v-else-if="currentStep === 2" class="step-panel">
        <h3>确认建模方案</h3>
        <div class="review-card">
          <div class="review-item">
            <span class="review-label">数据源:</span>
            <span class="review-value">{{ config.sourceType }}</span>
          </div>
          <div class="review-item">
            <span class="review-label">目标表:</span>
            <span class="review-value">{{ config.targetTable }}</span>
          </div>
          <div class="review-item">
            <span class="review-label">分层:</span>
            <span class="review-value">ODS → DWD → DIM → DWS</span>
          </div>
          <div class="review-item">
            <span class="review-label">调度:</span>
            <span class="review-value">{{ config.scheduleCycle }}</span>
          </div>
        </div>
        <button class="execute-btn" @click="executeModeling">
          开始建模 →
        </button>
      </div>

      <!-- Step 4: Progress -->
      <div v-else-if="currentStep === 3" class="step-panel">
        <ProgressTracker
          :steps="modelingSteps"
          :next-actions="nextActions"
          @action="handleAction"
        />
      </div>
    </div>

    <!-- Navigation buttons -->
    <div class="wizard-nav">
      <button
        v-if="currentStep > 0"
        class="nav-btn back"
        @click="currentStep--"
      >
        ← 上一步
      </button>
      <button
        v-if="currentStep < 2"
        class="nav-btn next"
        @click="currentStep++"
      >
        下一步 →
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import DataSourceSelector from './DataSourceSelector.vue'
import ProgressTracker from './ProgressTracker.vue'

const currentStep = ref(0)

interface WizardStep {
  label: string
  completed: boolean
}

const wizardSteps: WizardStep[] = [
  { label: '选择数据源', completed: false },
  { label: '配置表', completed: false },
  { label: '确认方案', completed: false },
  { label: '执行进度', completed: false },
]

interface Config {
  sourceType: string
  targetTable: string
  domain: string
  scheduleCycle: string
}

const config = ref<Config>({
  sourceType: '',
  targetTable: '',
  domain: '',
  scheduleCycle: 'day',
})

const modelingSteps = ref([
  { name: 'ODS 层', detail: '数据入仓', status: 'pending' as 'pending' | 'running' | 'completed' },
  { name: 'DWD 层', detail: '明细建模', status: 'pending' as 'pending' | 'running' | 'completed' },
  { name: 'DIM 层', detail: '维度建模', status: 'pending' as 'pending' | 'running' | 'completed' },
  { name: 'DWS 层', detail: '汇总建模', status: 'pending' as 'pending' | 'running' | 'completed' },
  { name: '调度配置', detail: 'Cron + 依赖', status: 'pending' as 'pending' | 'running' | 'completed' },
  { name: '词根校验', detail: '列名合规', status: 'pending' as 'pending' | 'running' | 'completed' },
])

const nextActions = [
  { id: 'inspect', label: '查看产物' },
  { id: 'schedule', label: '配置调度' },
  { id: 'publish', label: '提交发布' },
]

function onSourceSelected(sourceType: string) {
  config.value.sourceType = sourceType
  currentStep.value = 1
}

function jumpToStep(index: number) {
  if (index <= currentStep.value) {
    currentStep.value = index
  }
}

function executeModeling() {
  // Trigger actual modeling via backend API
  currentStep.value = 3
  // Simulate progress
  setTimeout(() => {
    modelingSteps.value[0].status = 'completed'
  }, 1000)
  setTimeout(() => {
    modelingSteps.value[1].status = 'completed'
  }, 2000)
}

function handleAction(actionId: string) {
  console.log('Action:', actionId)
}
</script>

<style scoped>
.modeling-wizard {
  padding: 24px;
  max-width: 900px;
  margin: 0 auto;
}

.wizard-header {
  text-align: center;
  margin-bottom: 32px;
}

.wizard-header h2 {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.wizard-header p {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 14px;
}

/* Step indicators */
.step-indicators {
  display: flex;
  justify-content: center;
  gap: 24px;
  margin-bottom: 32px;
}

.step-indicator {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.2s;
}

.step-indicator:hover {
  opacity: 0.8;
}

.step-indicator.active,
.step-indicator.completed {
  opacity: 1;
}

.step-number {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-size: 14px;
  font-weight: 700;
  border: 2px solid var(--color-border-primary);
  color: var(--color-text-tertiary);
  background: var(--color-bg-secondary);
}

.step-indicator.active .step-number {
  border-color: #6366F1;
  background: #6366F1;
  color: #fff;
}

.step-indicator.completed .step-number {
  border-color: #22C55E;
  background: #22C55E;
  color: #fff;
}

.step-label {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.step-indicator.active .step-label {
  color: var(--color-text-primary);
  font-weight: 600;
}

/* Step panels */
.step-panel {
  padding: 20px;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  background: var(--color-bg-secondary);
}

.step-panel h3 {
  margin: 0 0 16px;
  font-size: 18px;
  font-weight: 600;
  color: var(--color-text-primary);
}

/* Form */
.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.form-input,
.form-select {
  width: 100%;
  height: 40px;
  padding: 0 12px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
  font-size: 14px;
}

.form-input:focus,
.form-select:focus {
  outline: none;
  border-color: #6366F1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

/* Review card */
.review-card {
  display: grid;
  gap: 12px;
  margin-bottom: 20px;
}

.review-item {
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--color-bg-tertiary);
  border-radius: 8px;
}

.review-label {
  color: var(--color-text-tertiary);
  font-size: 13px;
}

.review-value {
  color: var(--color-text-primary);
  font-size: 13px;
  font-weight: 600;
}

.execute-btn {
  width: 100%;
  height: 48px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s;
}

.execute-btn:hover {
  transform: scale(1.02);
}

/* Navigation */
.wizard-nav {
  display: flex;
  justify-content: space-between;
  margin-top: 24px;
}

.nav-btn {
  padding: 10px 20px;
  border: 1px solid var(--color-border-primary);
  border-radius: 8px;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-btn:hover {
  border-color: #6366F1;
  color: #6366F1;
}

.nav-btn.next {
  background: #6366F1;
  color: #fff;
  border-color: #6366F1;
}

.nav-btn.next:hover {
  background: #4F46E5;
}
</style>
