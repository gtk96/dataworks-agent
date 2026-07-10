<template>
  <div class="quick-actions">
    <el-button
      v-for="action in actions"
      :key="action.label"
      size="small"
      @click="emit('action', action.prompt)"
    >
      <el-icon><component :is="action.icon" /></el-icon>
      {{ action.label }}
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { Grid, DataLine, Warning } from '@element-plus/icons-vue'

const emit = defineEmits<{
  action: [prompt: string]
}>()

const actions = [
  { label: '创建表', prompt: '帮我创建一张新表', icon: Grid },
  { label: '查询血缘', prompt: '查询表的血缘关系', icon: DataLine },
  { label: '检查状态', prompt: '检查最近任务执行状态', icon: Warning },
]
</script>

<style scoped>
.quick-actions {
  display: flex;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #eee;
  flex-wrap: wrap;
}
</style>
