<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" style="background: #1a1a2e; color: #eee">
      <div class="logo"><el-icon style="margin-right:6px;vertical-align:middle"><DataBoard /></el-icon>DW Agent</div>
      <el-menu
        :default-active="route.path"
        background-color="#1a1a2e"
        text-color="#bbb"
        active-text-color="#409EFF"
        router
      >
        <el-menu-item index="/">
          <el-icon><Monitor /></el-icon>
          <span>仪表盘</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon>
          <span>任务列表</span>
        </el-menu-item>
        <el-menu-item index="/tasks/create">
          <el-icon><Plus /></el-icon>
          <span>数仓建模</span>
        </el-menu-item>
        <el-menu-item index="/di">
          <el-icon><Connection /></el-icon>
          <span>数据集成</span>
        </el-menu-item>
        <el-menu-item index="/datasources">
          <el-icon><Coin /></el-icon>
          <span>数据源管理</span>
        </el-menu-item>
        <el-menu-item index="/governance">
          <el-icon><Share /></el-icon>
          <span>治理工具</span>
        </el-menu-item>
        <el-menu-item index="/semantic">
          <el-icon><Connection /></el-icon>
          <span>语义层</span>
        </el-menu-item>
        <el-menu-item index="/sync">
          <el-icon><Connection /></el-icon>
          <span>同步管理</span>
        </el-menu-item>
        <el-menu-item index="/reconciliation">
          <el-icon><Warning /></el-icon>
          <span>协调处置</span>
        </el-menu-item>
        <el-menu-item index="/ownership">
          <el-icon><User /></el-icon>
          <span>产权管理</span>
        </el-menu-item>
        <el-menu-item index="/bus-matrix">
          <el-icon><Grid /></el-icon>
          <span>总线矩阵</span>
        </el-menu-item>
        <el-menu-item index="/artifacts">
          <el-icon><Document /></el-icon>
          <span>产物管理</span>
        </el-menu-item>
        <el-menu-item index="/import">
          <el-icon><Upload /></el-icon>
          <span>批量导入</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
        <el-menu-item index="/dwd">
          <el-icon><EditPen /></el-icon>
          <span>DWD JSON 建模</span>
        </el-menu-item>
        <el-menu-item index="/pipeline">
          <el-icon><Connection /></el-icon>
          <span>管道队列</span>
        </el-menu-item>
        <el-menu-item index="/tasks/create-wizard">
          <el-icon><Plus /></el-icon>
          <span>任务创建向导</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header style="background: #fff; border-bottom: 1px solid #eee; display: flex; align-items: center; padding: 0 24px">
        <h2 style="margin: 0; font-size: 18px">{{ pageTitle }}</h2>
        <div style="margin-left: auto">
          <el-tag :type="healthTag" size="small">{{ healthText }}</el-tag>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '@/utils/request'
import { DataBoard, EditPen } from '@element-plus/icons-vue'

const route = useRoute()

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/': '仪表盘',
    '/tasks': '任务列表',
    '/tasks/create': '数仓建模',
    '/di': '数据集成',
    '/datasources': '数据源管理',
    '/governance': '治理与血缘',
    '/semantic': '语义层',
    '/sync': '同步管理',
    '/reconciliation': '协调处置',
    '/ownership': '产权管理',
    '/bus-matrix': '总线矩阵',
    '/artifacts': '产物管理',
    '/import': '批量导入',
    '/settings': '系统设置',
    '/dwd': 'DWD JSON 建模',
    '/pipeline': '管道队列',
    '/tasks/create-wizard': '任务创建向导',
  }
  // 子路由前缀匹配（如 /tasks/:id → 任务列表）
  for (const [prefix, title] of Object.entries(map)) {
    if (route.path === prefix || route.path.startsWith(prefix + '/')) {
      return title
    }
  }
  return 'DW Agent'
})

const healthTag = ref<'success' | 'warning' | 'danger'>('warning')
const healthText = ref('检查中...')

onMounted(async () => {
  try {
    const h = await request<{ status: string }>('/api/health')
    healthText.value = h.status === 'ok' ? '系统正常' : '服务降级'
    healthTag.value = h.status === 'ok' ? 'success' : 'warning'
  } catch {
    healthText.value = '无法连接'
    healthTag.value = 'danger'
  }
})
</script>

<style scoped>
.logo {
  padding: 20px 16px;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  border-bottom: 1px solid #333;
}
.el-menu { border-right: none; }
</style>
