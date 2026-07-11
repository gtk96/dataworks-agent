<template>
  <div class="agent-home">
    <section class="hero-card">
      <div class="hero-copy">
        <el-tag class="hero-tag" type="success" effect="dark">Agent-first</el-tag>
        <h1>把目标交给 Agent，自动完成 DataWorks 建模规划</h1>
        <p>
          不再先选择工具、填写多个表单。直接描述业务或数据目标，Agent 会理解需求、拆解计划、生成产物草稿、检查风险，并在需要真实发布时进入审批门禁。
        </p>
      </div>
      <div class="hero-metrics">
        <div class="metric-card">
          <span class="metric-value">理解目标</span>
          <span class="metric-label">抽取表、层级、指标、调度和上下文</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">拆解计划</span>
          <span class="metric-label">自动生成 DataWorks 执行步骤和依赖顺序</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">生成产物</span>
          <span class="metric-label">产出 DDL、DML、FlowSpec、血缘和风险报告</span>
        </div>
        <div class="metric-card">
          <span class="metric-value">审批发布</span>
          <span class="metric-label">写入、覆盖、发布统一进入 Publish Gate</span>
        </div>
      </div>
    </section>

    <AgentChat />
  </div>
</template>

<script setup lang="ts">
import AgentChat from '@/components/agent/AgentChat.vue'
</script>

<style scoped>
.agent-home {
  min-height: calc(100vh - 96px);
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(64, 158, 255, 0.14), transparent 34%),
    linear-gradient(135deg, #f7f9ff 0%, #eef3ff 48%, #f8fbff 100%);
  border-radius: 24px;
}

.hero-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 620px;
  gap: 24px;
  align-items: stretch;
  margin-bottom: 22px;
  padding: 28px;
  border: 1px solid rgba(98, 128, 210, 0.14);
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 24px 70px rgba(31, 45, 91, 0.12);
  backdrop-filter: blur(18px);
}

.hero-tag {
  border: none;
  margin-bottom: 14px;
}

.hero-copy h1 {
  margin: 0 0 12px;
  font-size: 38px;
  line-height: 1.15;
  letter-spacing: -0.04em;
  color: #18233f;
}

.hero-copy p {
  max-width: 760px;
  margin: 0;
  color: #667085;
  font-size: 16px;
  line-height: 1.8;
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.metric-card {
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 116px;
  padding: 18px;
  border-radius: 22px;
  background: linear-gradient(180deg, #ffffff 0%, #f4f7ff 100%);
  border: 1px solid rgba(64, 158, 255, 0.14);
}

.metric-value {
  color: #2456d6;
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.03em;
}

.metric-label {
  margin-top: 8px;
  color: #667085;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 1280px) {
  .hero-card {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .agent-home {
    padding: 12px;
  }

  .hero-card {
    padding: 20px;
  }

  .hero-copy h1 {
    font-size: 28px;
  }

  .hero-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
