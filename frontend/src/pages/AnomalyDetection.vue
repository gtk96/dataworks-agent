<template>
  <div class="anomaly-page">
    <div class="page-header">
      <h2>异常排查</h2>
      <p class="subtitle">分析节点失败原因，查看日志并提供修复建议</p>
    </div>

    <!-- Input section -->
    <div class="input-section">
      <div class="input-group">
        <label>任务名称 / 节点 ID</label>
        <input
          v-model="taskId"
          placeholder="例如: node_12345 或 订单日报"
          @keyup.enter="startDiagnosis"
        />
      </div>
      <div class="input-group">
        <label>工作空间（可选）</label>
        <input
          v-model="workspace"
          placeholder="留空则使用默认配置"
        />
      </div>
      <button class="diagnose-btn" :disabled="!taskId || isRunning" @click="startDiagnosis">
        <svg v-if="!isRunning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
        </svg>
        <svg v-else class="spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/>
        </svg>
        {{ isRunning ? '排查中...' : '开始排查' }}
      </button>
    </div>

    <!-- Results -->
    <div v-if="results.length" class="results-section">
      <div v-for="(result, index) in results" :key="index" class="result-card" :class="result.severity">
        <div class="result-header">
          <span class="severity-badge" :class="result.severity">{{ severityLabel(result.severity) }}</span>
          <strong>{{ result.title }}</strong>
        </div>
        <p class="result-desc">{{ result.description }}</p>
        <div v-if="result.log_snippet" class="log-snippet">
          <pre>{{ result.log_snippet }}</pre>
        </div>
        <div v-if="result.suggestion" class="suggestion">
          <strong>💡 建议：</strong>
          <p>{{ result.suggestion }}</p>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="!isRunning" class="empty-state">
      <svg viewBox="0 0 48 48" fill="none">
        <rect width="48" height="48" rx="12" fill="rgba(251, 191, 36, 0.1)"/>
        <path d="M24 16v10" stroke="#F59E0B" stroke-width="2.5" stroke-linecap="round"/>
        <circle cx="24" cy="31" r="1.5" fill="#F59E0B"/>
      </svg>
      <p>输入任务名称或节点 ID，开始排查异常</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const taskId = ref('')
const workspace = ref('')
const isRunning = ref(false)
const results = ref<Array<{
  severity: 'critical' | 'warning' | 'info'
  title: string
  description: string
  log_snippet?: string
  suggestion?: string
}>>([])

function severityLabel(severity: string): string {
  const labels: Record<string, string> = {
    critical: '严重',
    warning: '警告',
    info: '信息',
  }
  return labels[severity] ?? severity
}

async function startDiagnosis() {
  if (!taskId.value || isRunning.value) return
  isRunning.value = true
  results.value = []

  try {
    // Call the agent chat with diagnosis intent
    const resp = await fetch('/agent/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: `请排查 DataWorks 中节点 "${taskId.value}" 的异常原因，查看运行日志，定位问题并提供修复建议。${workspace.value ? `工作空间: ${workspace.value}` : ''}`,
        execution_mode: 'auto',
        initialize_data: false,
        publish: false,
      }),
    })

    const data = await resp.json()

    if (data.success) {
      results.value = [{
        severity: 'info',
        title: data.message,
        description: 'Agent 已完成初步分析',
        suggestion: data.data?.plan?.summary || '请查看上方分析结果',
      }]
    } else {
      results.value = [{
        severity: 'critical',
        title: '排查失败',
        description: data.error || '未知错误',
      }]
    }
  } catch (err) {
    results.value = [{
      severity: 'critical',
      title: '网络错误',
      description: err instanceof Error ? err.message : '请求失败',
    }]
  } finally {
    isRunning.value = false
  }
}
</script>

<style scoped>
.anomaly-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 24px 0;
}

.page-header {
  margin-bottom: 32px;
}

.page-header h2 {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.subtitle {
  margin-top: 6px;
  color: var(--color-text-tertiary);
  font-size: 14px;
}

.input-section {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 32px;
}

.input-group {
  flex: 1;
  min-width: 200px;
}

.input-group label {
  display: block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-secondary);
}

.input-group input {
  width: 100%;
  padding: 10px 14px;
  border: 1.5px solid var(--color-border-primary);
  border-radius: 10px;
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  font-size: 14px;
  transition: border-color 0.2s;
}

.input-group input:focus {
  outline: none;
  border-color: #6366F1;
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.diagnose-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 24px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s, opacity 0.15s;
  align-self: flex-end;
}

.diagnose-btn:hover:not(:disabled) {
  transform: translateY(-1px);
}

.diagnose-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.diagnose-btn svg {
  width: 18px;
  height: 18px;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.results-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.result-card {
  padding: 20px;
  border: 1.5px solid var(--color-border-primary);
  border-radius: 14px;
  background: var(--color-bg-secondary);
}

.result-card.critical {
  border-color: rgba(248, 113, 113, 0.3);
  background: rgba(248, 113, 113, 0.05);
}

.result-card.warning {
  border-color: rgba(251, 191, 36, 0.3);
  background: rgba(251, 191, 36, 0.05);
}

.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.result-header strong {
  color: var(--color-text-primary);
  font-size: 15px;
}

.severity-badge {
  padding: 2px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
}

.severity-badge.critical {
  background: rgba(248, 113, 113, 0.15);
  color: #F87171;
}

.severity-badge.warning {
  background: rgba(251, 191, 36, 0.15);
  color: #FBBF24;
}

.severity-badge.info {
  background: rgba(99, 102, 241, 0.15);
  color: #818CF8;
}

.result-desc {
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.6;
  margin-bottom: 12px;
}

.log-snippet {
  margin: 12px 0;
  padding: 12px 14px;
  background: var(--color-bg-code);
  border-radius: 8px;
  overflow-x: auto;
}

.log-snippet pre {
  color: #F87171;
  font-family: var(--font-family-mono);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
}

.suggestion {
  margin-top: 12px;
  padding: 12px 14px;
  background: rgba(34, 197, 94, 0.08);
  border-radius: 8px;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.suggestion strong {
  color: #22C55E;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;
}

.empty-state svg {
  width: 48px;
  height: 48px;
  margin-bottom: 16px;
}

.empty-state p {
  color: var(--color-text-tertiary);
  font-size: 14px;
}
</style>
