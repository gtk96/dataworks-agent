<template>
  <div class="data-source-selector">
    <div class="selector-header">
      <h3>选择数据源类型</h3>
      <p class="subtitle">选择您的数据源，Agent 将自动规划全链路建模方案</p>
    </div>

    <div class="source-grid">
      <!-- OSS -->
      <button
        class="source-card"
        :class="{ active: selected === 'oss' }"
        @click="selectSource('oss')"
      >
        <div class="source-icon oss">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <div class="source-info">
          <strong>OSS 对象存储</strong>
          <span>JSON / CSV / Parquet / ORC</span>
        </div>
        <div class="source-check">
          <svg v-if="selected === 'oss'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </button>

      <!-- Hologres -->
      <button
        class="source-card"
        :class="{ active: selected === 'holo' }"
        @click="selectSource('holo')"
      >
        <div class="source-icon holo">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
          </svg>
        </div>
        <div class="source-info">
          <strong>Hologres 实时数仓</strong>
          <span>实时入仓 / 维度关联</span>
        </div>
        <div class="source-check">
          <svg v-if="selected === 'holo'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </button>

      <!-- MySQL -->
      <button
        class="source-card"
        :class="{ active: selected === 'mysql' }"
        @click="selectSource('mysql')"
      >
        <div class="source-icon mysql">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/>
            <path d="M2 17l10 5 10-5"/>
            <path d="M2 12l10 5 10-5"/>
          </svg>
        </div>
        <div class="source-info">
          <strong>MySQL / PolarDB</strong>
          <span>关系型数据库 / 全量增量</span>
        </div>
        <div class="source-check">
          <svg v-if="selected === 'mysql'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </button>

      <!-- PostgreSQL -->
      <button
        class="source-card"
        :class="{ active: selected === 'postgres' }"
        @click="selectSource('postgres')"
      >
        <div class="source-icon postgres">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/>
            <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>
          </svg>
        </div>
        <div class="source-info">
          <strong>PostgreSQL</strong>
          <span>开源关系型数据库</span>
        </div>
        <div class="source-check">
          <svg v-if="selected === 'postgres'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
            <polyline points="20 6 9 17 4 12"/>
          </svg>
        </div>
      </button>
    </div>

    <!-- Selected source details -->
    <div v-if="selected" class="source-details">
      <div class="detail-header">
        <h4>{{ detailTitle }}</h4>
        <button class="clear-btn" @click="selected = null">×</button>
      </div>
      <p class="detail-desc">{{ detailDesc }}</p>
      <button class="continue-btn" @click="$emit('continue', selected)">
        继续建模 →
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const selected = ref<string | null>(null)

const emit = defineEmits<{
  continue: [sourceType: string]
}>()

const sourceDetails: Record<string, { title: string; desc: string }> = {
  oss: {
    title: 'OSS 对象存储数据入仓',
    desc: '支持 JSON、CSV、Parquet、ORC 等多种文件格式，自动发现分区信息，创建外部表并同步到 MaxCompute ODS 层。',
  },
  holo: {
    title: 'Hologres 实时数据入仓',
    desc: '从 Hologres 实时数仓同步数据到 MaxCompute，支持全量/增量同步，自动推断字段类型和主键。',
  },
  mysql: {
    title: 'MySQL / PolarDB 数据入仓',
    desc: '通过 DataWorks 数据集成（DataX）将 MySQL/PolarDB 数据同步到 MaxCompute，支持全量和基于时间戳的增量同步。',
  },
  postgres: {
    title: 'PostgreSQL 数据入仓',
    desc: '通过 DataWorks 数据集成将 PostgreSQL 数据同步到 MaxCompute，支持全量和增量同步模式。',
  },
}

const detailTitle = computed(() => selected.value ? sourceDetails[selected.value]?.title || '' : '')
const detailDesc = computed(() => selected.value ? sourceDetails[selected.value]?.desc || '' : '')

function selectSource(type: string) {
  selected.value = selected.value === type ? null : type
}
</script>

<style scoped>
.data-source-selector {
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
}

.selector-header {
  text-align: center;
  margin-bottom: 32px;
}

.selector-header h3 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.subtitle {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 14px;
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.source-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1.5px solid var(--color-border-primary);
  border-radius: 12px;
  background: var(--color-bg-secondary);
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
}

.source-card:hover {
  border-color: #6366F1;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.15);
}

.source-card.active {
  border-color: #6366F1;
  background: rgba(99, 102, 241, 0.08);
}

.source-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}

.source-icon.oss { background: rgba(99, 102, 241, 0.1); color: #6366F1; }
.source-icon.holo { background: rgba(34, 197, 94, 0.1); color: #22C55E; }
.source-icon.mysql { background: rgba(251, 191, 36, 0.1); color: #F59E0B; }
.source-icon.postgres { background: rgba(168, 85, 247, 0.1); color: #A855F7; }

.source-icon svg {
  width: 22px;
  height: 22px;
}

.source-info {
  flex: 1;
  min-width: 0;
}

.source-info strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.source-info span {
  display: block;
  font-size: 11px;
  color: var(--color-text-tertiary);
  margin-top: 2px;
}

.source-check {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.2s;
}

.source-card.active .source-check {
  opacity: 1;
  color: #6366F1;
}

.source-check svg {
  width: 20px;
  height: 20px;
}

/* Details section */
.source-details {
  padding: 20px;
  border: 1px solid var(--color-border-primary);
  border-radius: 12px;
  background: var(--color-bg-secondary);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.detail-header h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.clear-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--color-text-tertiary);
  cursor: pointer;
  font-size: 18px;
  display: grid;
  place-items: center;
}

.clear-btn:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.detail-desc {
  margin: 0 0 16px;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.continue-btn {
  width: 100%;
  height: 44px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366F1, #4F46E5);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.15s;
}

.continue-btn:hover {
  transform: scale(1.02);
}

/* Responsive */
@media (max-width: 640px) {
  .source-grid {
    grid-template-columns: 1fr;
  }
}
</style>
