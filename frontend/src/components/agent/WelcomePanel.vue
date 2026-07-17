<template>
  <div class="welcome">
    <div class="welcome-icon">
      <svg viewBox="0 0 48 48" fill="none">
        <rect width="48" height="48" rx="14" fill="url(#grad)"/>
        <path d="M16 24l6 6 12-12" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
        <defs>
          <linearGradient id="grad" x1="0" y1="0" x2="48" y2="48">
            <stop stop-color="#6366F1"/>
            <stop offset="1" stop-color="#8B5CF6"/>
          </linearGradient>
        </defs>
      </svg>
    </div>
    <h1>DataWorks Agent</h1>
    <p>一句话描述目标，Agent 自动规划并执行。</p>

    <div class="prompt-grid">
      <button
        v-for="prompt in prompts"
        :key="prompt.title"
        class="prompt-card"
        @click="$emit('select', prompt.text)"
      >
        <div class="prompt-icon" :class="prompt.color">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path v-if="prompt.icon === 'model'" d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
            <path v-else-if="prompt.icon === 'query'" d="M3 3v18h18"/>
            <path v-else-if="prompt.icon === 'alert'" d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
            <path v-else d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <div class="prompt-content">
          <strong>{{ prompt.title }}</strong>
          <span>{{ prompt.desc }}</span>
        </div>
        <svg class="prompt-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M5 12h14M12 5l7 7-7 7"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Prompt {
  title: string
  desc: string
  text: string
  icon: 'model' | 'query' | 'alert' | 'chat'
  color: 'blue' | 'green' | 'orange' | 'purple'
}

const prompts: Prompt[] = [
  {
    title: '全链路建模',
    desc: 'ODS→DWD→DIM→DWS 一键搭建完整数据链路',
    text: '请帮我搭建从 ads_data 到 dw_order 的 ODS、DWD、DIM、DWS 全链路建模，先给出规划再逐步执行。',
    icon: 'model',
    color: 'blue',
  },
  {
    title: '智能问数',
    desc: '自然语言查询业务数据，自动生成 SQL 并展示结果',
    text: '请帮我查询订单表的数据量，并按日期统计，如果未通过请帮我确认维度。',
    icon: 'query',
    color: 'green',
  },
  {
    title: '异常排查',
    desc: '分析节点失败原因，查看日志并提供修复建议',
    text: '请排查 DataWorks 中某节点的失败原因，查看运行日志，定位异常并提供修复建议。',
    icon: 'alert',
    color: 'orange',
  },
  {
    title: '对话咨询',
    desc: '询问数据仓库相关问题，获取专业解答',
    text: '我想了解关于数据仓库建模的最佳实践。',
    icon: 'chat',
    color: 'purple',
  },
]

defineEmits<{
  select: [text: string]
}>()
</script>

<style scoped>
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 40px 20px 20px;
  max-width: 720px;
  margin: 0 auto;
}

.welcome-icon {
  width: 56px;
  height: 56px;
  margin-bottom: 20px;
}

.welcome h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.02em;
}

.welcome > p {
  margin: 10px 0 32px;
  color: var(--color-text-secondary);
  font-size: 15px;
  line-height: 1.6;
}

.prompt-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  width: 100%;
  text-align: left;
}

.prompt-card {
  display: grid;
  grid-template-columns: 36px 1fr 20px;
  grid-template-rows: auto auto;
  gap: 10px;
  align-items: center;
  padding: 14px 16px;
  border: 1.5px solid var(--color-border-primary);
  border-radius: 14px;
  background: var(--color-bg-secondary);
  cursor: pointer;
  transition: all 0.2s;
}

.prompt-card:hover {
  border-color: #6366F1;
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.12);
}

.prompt-icon {
  grid-row: 1 / 3;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
}

.prompt-icon.blue { background: rgba(99, 102, 241, 0.1); color: #6366F1; }
.prompt-icon.green { background: rgba(34, 197, 94, 0.1); color: #22C55E; }
.prompt-icon.orange { background: rgba(251, 191, 36, 0.1); color: #F59E0B; }
.prompt-icon.purple { background: rgba(168, 85, 247, 0.1); color: #A855F7; }

.prompt-icon svg {
  width: 20px;
  height: 20px;
}

.prompt-content strong {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text-primary);
}

.prompt-content span {
  display: block;
  font-size: 12px;
  color: var(--color-text-tertiary);
  line-height: 1.4;
  margin-top: 2px;
}

.prompt-arrow {
  grid-column: 3;
  grid-row: 1 / 3;
  color: var(--color-text-tertiary);
  width: 16px;
  height: 16px;
}
</style>
