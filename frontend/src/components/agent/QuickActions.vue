<template>
  <div class="quick-actions">
    <el-button v-for="action in actions" :key="action.label" round @click="emit('action', action.prompt)">
      <el-icon><component :is="action.icon" /></el-icon>
      {{ action.label }}
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { DataLine, Grid, Warning } from '@element-plus/icons-vue'

const emit = defineEmits<{
  action: [prompt: string]
}>()

const actions = [
  { label: '建模草案', prompt: '帮我基于 ods_order 设计 DWD 明细模型，并生成 DDL、DML 和调度建议', icon: Grid },
  { label: '血缘分析', prompt: '分析 ods_user 的上下游血缘影响范围，并给出风险摘要', icon: DataLine },
  { label: '任务诊断', prompt: '排查最近一个 Agent 任务失败原因，并给出安全恢复方案', icon: Warning },
]
</script>

<style scoped>
.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #eef2ff;
}
</style>
