<template>
  <el-container class="shell">
    <el-aside width="236px" class="sidebar">
      <div class="brand">
        <div class="brand-icon"><DataBoard /></div>
        <div>
          <strong>DW Agent</strong>
          <span>DataWorks 智能建模平台</span>
        </div>
      </div>

      <el-menu
        :default-active="route.path"
        background-color="transparent"
        text-color="#9aa4b2"
        active-text-color="#ffffff"
        router
      >
        <el-menu-item index="/" class="primary-entry">
          <el-icon><Cpu /></el-icon>
          <span>Agent 工作台</span>
        </el-menu-item>
        <el-menu-item index="/tasks">
          <el-icon><List /></el-icon>
          <span>任务与运行</span>
        </el-menu-item>
        <el-menu-item index="/artifacts">
          <el-icon><Document /></el-icon>
          <span>产物中心</span>
        </el-menu-item>

        <el-sub-menu index="advanced">
          <template #title>
            <el-icon><MoreFilled /></el-icon>
            <span>高级工具</span>
          </template>
          <el-menu-item index="/tasks/create"><el-icon><Plus /></el-icon><span>建模任务</span></el-menu-item>
          <el-menu-item index="/di"><el-icon><Connection /></el-icon><span>数据集成</span></el-menu-item>
          <el-menu-item index="/datasources"><el-icon><Coin /></el-icon><span>数据源管理</span></el-menu-item>
          <el-menu-item index="/governance"><el-icon><Share /></el-icon><span>治理中心</span></el-menu-item>
          <el-menu-item index="/semantic"><el-icon><Connection /></el-icon><span>语义中心</span></el-menu-item>
          <el-menu-item index="/sync"><el-icon><Connection /></el-icon><span>环境同步</span></el-menu-item>
          <el-menu-item index="/reconciliation"><el-icon><Warning /></el-icon><span>稽核处置</span></el-menu-item>
          <el-menu-item index="/ownership"><el-icon><User /></el-icon><span>归属管理</span></el-menu-item>
          <el-menu-item index="/bus-matrix"><el-icon><Grid /></el-icon><span>业务矩阵</span></el-menu-item>
          <el-menu-item index="/import"><el-icon><Upload /></el-icon><span>SQL 导入</span></el-menu-item>
          <el-menu-item index="/dwd"><el-icon><EditPen /></el-icon><span>DWD JSON 工作台</span></el-menu-item>
          <el-menu-item index="/pipeline"><el-icon><Connection /></el-icon><span>管道队列</span></el-menu-item>
          <el-menu-item index="/tasks/create-wizard"><el-icon><Plus /></el-icon><span>建模向导</span></el-menu-item>
          <el-menu-item index="/settings"><el-icon><Setting /></el-icon><span>系统设置</span></el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="topbar">
        <div>
          <p class="topbar-kicker">DataWorks Agent Platform</p>
          <h2>{{ pageTitle }}</h2>
        </div>
        <div class="topbar-status">
          <el-tag type="primary" round effect="plain">Agent-first</el-tag>
          <el-tag type="warning" round effect="plain">Dry-run 安全模式</el-tag>
          <el-tag type="success" round effect="plain">Publish Gate 已启用</el-tag>
          <el-tag :type="healthTag" round>{{ healthText }}</el-tag>
        </div>
      </el-header>
      <el-main class="main"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { request } from '@/utils/request'
import {
  Coin,
  Connection,
  Cpu,
  DataBoard,
  Document,
  EditPen,
  Grid,
  List,
  MoreFilled,
  Plus,
  Setting,
  Share,
  Upload,
  User,
  Warning,
} from '@element-plus/icons-vue'

const route = useRoute()

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/': 'Agent 工作台',
    '/tasks': '任务与运行',
    '/tasks/create': '建模任务',
    '/di': '数据集成',
    '/datasources': '数据源管理',
    '/governance': '治理中心',
    '/semantic': '语义中心',
    '/sync': '环境同步',
    '/reconciliation': '稽核处置',
    '/ownership': '归属管理',
    '/bus-matrix': '业务矩阵',
    '/artifacts': '产物中心',
    '/import': 'SQL 导入',
    '/settings': '系统设置',
    '/dwd': 'DWD JSON 工作台',
    '/pipeline': '管道队列',
    '/tasks/create-wizard': '建模向导',
  }
  const entries = Object.entries(map).sort((a, b) => b[0].length - a[0].length)
  for (const [prefix, title] of entries) {
    if (route.path === prefix || route.path.startsWith(prefix + '/')) return title
  }
  return 'DW Agent'
})

const healthTag = ref<'success' | 'warning' | 'danger'>('warning')
const healthText = ref('检测中')

onMounted(async () => {
  try {
    const h = await request<{ status: string }>('/api/health')
    healthText.value = h.status === 'ok' ? '服务正常' : '服务异常'
    healthTag.value = h.status === 'ok' ? 'success' : 'warning'
  } catch {
    healthText.value = '服务异常'
    healthTag.value = 'danger'
  }
})
</script>

<style scoped>
.shell {
  height: 100vh;
  background: #f4f7fb;
}

.sidebar {
  padding: 18px 14px;
  background: linear-gradient(180deg, #101828 0%, #111c35 100%);
  color: #fff;
}

.brand {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 10px 10px 22px;
}

.brand-icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #2456d6, #409eff);
  box-shadow: 0 14px 32px rgba(64, 158, 255, 0.24);
}

.brand strong,
.brand span {
  display: block;
}

.brand strong {
  font-size: 18px;
  letter-spacing: -0.02em;
}

.brand span {
  margin-top: 3px;
  color: #98a2b3;
  font-size: 12px;
}

.el-menu {
  border-right: none;
}

.el-menu :deep(.el-menu-item),
.el-menu :deep(.el-sub-menu__title) {
  height: 44px;
  margin: 4px 0;
  border-radius: 14px;
}

.el-menu :deep(.el-menu-item.is-active) {
  background: rgba(64, 158, 255, 0.18);
}

.primary-entry {
  margin-top: 8px;
  background: rgba(64, 158, 255, 0.1);
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  height: 72px;
  padding: 0 28px;
  border-bottom: 1px solid #e8edf6;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(16px);
}

.topbar-status {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.topbar-kicker {
  margin: 0 0 3px;
  color: #98a2b3;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.topbar h2 {
  margin: 0;
  color: #18233f;
  font-size: 20px;
  letter-spacing: -0.02em;
}

.main {
  padding: 20px;
  overflow: auto;
}

@media (max-width: 1180px) {
  .topbar-status .el-tag:nth-child(-n + 3) {
    display: none;
  }
}
</style>
