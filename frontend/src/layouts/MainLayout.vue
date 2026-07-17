<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="logo">
          <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect width="32" height="32" rx="8" fill="url(#logoGradient)"/>
            <text x="16" y="22" text-anchor="middle" fill="#fff" font-weight="800" font-size="16" font-family="Inter,sans-serif">D</text>
            <defs>
              <linearGradient id="logoGradient" x1="0" y1="0" x2="32" y2="32">
                <stop stop-color="#60A5FA"/>
                <stop offset="1" stop-color="#A78BFA"/>
              </linearGradient>
            </defs>
          </svg>
          <div class="logo-text">
            <span class="logo-title">DataWorks Agent</span>
            <span class="logo-subtitle">智能数仓工作台</span>
          </div>
        </div>
      </div>

      <nav class="nav-menu">
        <div class="nav-section">
          <span class="nav-section-title">核心功能</span>
          <router-link to="/" class="nav-item" :class="{ active: route.path === '/' }">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
            <span>Agent 会话</span>
          </router-link>
          <router-link to="/anomaly" class="nav-item" :class="{ active: route.path.startsWith('/anomaly') }">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
            </svg>
            <span>异常排查</span>
          </router-link>
          <router-link to="/tasks" class="nav-item" :class="{ active: route.path.startsWith('/tasks') && !route.path.includes('create') }">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="16" y1="13" x2="8" y2="13"/>
              <line x1="16" y1="17" x2="8" y2="17"/>
              <polyline points="10 9 9 9 8 9"/>
            </svg>
            <span>任务管理</span>
          </router-link>
          <router-link to="/artifacts" class="nav-item" :class="{ active: route.path.startsWith('/artifacts') }">
            <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
            </svg>
            <span>产物管理</span>
          </router-link>
        </div>

        <template v-if="enableAdvancedTools">
          <div class="nav-section">
            <span class="nav-section-title">高级功能</span>
            <router-link v-for="item in advancedItems" :key="item.path" :to="item.path" class="nav-item" :class="{ active: route.path.startsWith(item.path) }">
              <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path :d="item.iconPath"/>
              </svg>
              <span>{{ item.title }}</span>
            </router-link>
          </div>
        </template>
      </nav>

      <div class="sidebar-footer">
        <router-link v-if="enableAdvancedTools" to="/settings" class="nav-item settings-link">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
          <span>设置</span>
        </router-link>
        <div class="workspace-card">
          <div class="workspace-avatar">DW</div>
          <div class="workspace-info">
            <span class="workspace-name">数仓工作空间</span>
            <span class="workspace-status">Publish Gate 已启用</span>
          </div>
        </div>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <!-- Top Bar -->
      <header class="topbar">
        <div class="topbar-left">
          <h1 class="page-title">{{ pageTitle }}</h1>
          <span v-if="route.path === '/'" class="badge badge-info">Agent-first</span>
        </div>
        <div class="topbar-right">
          <div class="health-status" :class="healthTag">
            <span class="health-dot"></span>
            <span class="health-text">{{ healthText }}</span>
          </div>
        </div>
      </header>

      <!-- Page Content -->
      <div class="page-content">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const enableAdvancedTools = import.meta.env.VITE_ENABLE_ADVANCED_TOOLS === 'true'

const advancedItems = [
  { path: '/modeling', title: '全链路建模', iconPath: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' },
          { path: '/anomaly', title: '异常排查', iconPath: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' },
  { path: '/tasks/create', title: '正向建模', iconPath: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' },
  { path: '/di', title: '数据集成', iconPath: 'M22 12h-4l-3 9L9 3l-3 9H2' },
  { path: '/datasources', title: '数据源', iconPath: 'M4 7V4a2 2 0 0 1 2-2h8.5L20 7.5V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3' },
  { path: '/governance', title: '数据治理', iconPath: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' },
  { path: '/semantic', title: '语义管理', iconPath: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z' },
  { path: '/import', title: 'SQL 导入', iconPath: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4' },
]

const pageTitle = computed(() => {
  const map: Record<string, string> = {
    '/': 'Agent 会话',
    '/anomaly': '异常排查',
    '/tasks': '任务管理',
    '/artifacts': '产物管理',
    '/settings': '设置',
  }
  return map[route.path] ?? advancedItems.find((item) => route.path.startsWith(item.path))?.title ?? 'DataWorks Agent'
})

const healthTag = ref('checking')
const healthText = ref('检测中...')

onMounted(async () => {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) throw new Error('unhealthy')
    healthTag.value = 'online'
    healthText.value = '服务正常'
  } catch {
    healthTag.value = 'degraded'
    healthText.value = '服务降级'
  }
})
</script>

<style scoped>
.app-layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg-primary);
}

/* Sidebar */
.sidebar {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  width: var(--sidebar-width);
  background: var(--color-bg-secondary);
  border-right: 1px solid var(--color-border-primary);
  display: flex;
  flex-direction: column;
  z-index: var(--z-sticky);
  transition: width var(--transition-normal);
}

.sidebar-header {
  padding: var(--space-5);
  border-bottom: 1px solid var(--color-border-secondary);
}

.logo {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.logo svg {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
}

.logo-text {
  display: flex;
  flex-direction: column;
}

.logo-title {
  font-size: var(--font-size-md);
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}

.logo-subtitle {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
  margin-top: 2px;
}

/* Navigation */
.nav-menu {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-4) 0;
}

.nav-section {
  padding: var(--space-2) var(--space-4);
}

.nav-section-title {
  display: block;
  padding: var(--space-3) var(--space-4);
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--color-text-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  margin: var(--space-1) 0;
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  text-decoration: none;
  font-size: var(--font-size-sm);
  font-weight: 500;
  transition: all var(--transition-fast);
  cursor: pointer;
}

.nav-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-text-primary);
}

.nav-item.active {
  background: var(--gradient-subtle);
  color: var(--color-accent-blue);
}

.nav-icon {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

/* Sidebar Footer */
.sidebar-footer {
  padding: var(--space-4);
  border-top: 1px solid var(--color-border-secondary);
}

.settings-link {
  margin-bottom: var(--space-3);
}

.workspace-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-md);
}

.workspace-avatar {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--gradient-brand);
  border-radius: var(--radius-md);
  color: white;
  font-size: var(--font-size-sm);
  font-weight: 700;
  flex-shrink: 0;
}

.workspace-info {
  display: flex;
  flex-direction: column;
}

.workspace-name {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-primary);
}

.workspace-status {
  font-size: var(--font-size-xs);
  color: var(--color-text-tertiary);
}

/* Main Content */
.main-content {
  flex: 1;
  margin-left: var(--sidebar-width);
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* Top Bar */
.topbar {
  position: sticky;
  top: 0;
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-8);
  background: rgba(15, 18, 24, 0.9);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--color-border-primary);
  z-index: var(--z-sticky);
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.page-title {
  font-size: var(--font-size-xl);
  font-weight: 600;
  color: var(--color-text-primary);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.health-status {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: 500;
  color: var(--color-text-secondary);
}

.health-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--color-accent-green);
  box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.2);
}

.health-status.checking .health-dot {
  background: var(--color-accent-orange);
  box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.2);
}

.health-status.degraded .health-dot {
  background: var(--color-accent-red);
  box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.2);
}

/* Page Content */
.page-content {
  flex: 1;
  padding: var(--space-8);
  overflow-y: auto;
}

/* Responsive */
@media (max-width: 768px) {
  .sidebar {
    width: var(--sidebar-collapsed-width);
  }

  .logo-text,
  .nav-item span,
  .nav-section-title,
  .workspace-info {
    display: none;
  }

  .nav-item {
    justify-content: center;
    padding: var(--space-4);
  }

  .nav-icon {
    margin: 0;
  }

  .workspace-card {
    justify-content: center;
  }

  .main-content {
    margin-left: var(--sidebar-collapsed-width);
  }

  .topbar {
    padding: 0 var(--space-4);
  }

  .page-content {
    padding: var(--space-4);
  }
}
</style>
