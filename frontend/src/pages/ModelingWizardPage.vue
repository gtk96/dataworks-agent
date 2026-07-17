<template>
  <div class="modeling-page">
    <div class="page-header">
      <h1>🚀 全链路建模向导</h1>
      <p>从数据源选择到调度配置，一站式完成数仓建模</p>
    </div>
    <ModelingWizard />
  </div>
</template>

<script setup lang="ts">
import ModelingWizard from '@/components/modeling/ModelingWizard.vue'
</script>

<style scoped>
.modeling-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
}

.page-header {
  text-align: center;
  margin-bottom: 32px;
}

.page-header h1 {
  margin: 0 0 8px;
  font-size: 32px;
  font-weight: 700;
  color: var(--color-text-primary);
}

.page-header p {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: 15px;
}
</style>
