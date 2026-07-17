<template>
  <div class="app-layout">
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
        <router-link to="/" class="nav-item" :class="{ active: route.path === '/' }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span>Agent 会话</span>
        </router-link>
        <router-link to="/tasks" class="nav-item" :class="{ active: route.path.startsWith('/tasks') }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
          <span>任务管理</span>
        </router-link>
        <router-link to="/anomaly" class="nav-item" :class="{ active: route.path.startsWith('/anomaly') }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
          <span>异常排查</span>
        </router-link>
        <router-link to="/datasources" class="nav-item" :class="{ active: route.path.startsWith('/datasources') }">
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
          <span>数据源</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="health-status" :class="healthTag">
          <span class="health-dot"></span>
          <span class="health-text">{{ healthText }}</span>
        </div>
      </div>
    </aside>
    <main class="main-content">
      <header class="topbar">
        <h1 class="page-title">{{ pageTitle }}</h1>
      </header>
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
const pageTitle = computed(() => ({ '/': 'Agent 会话', '/anomaly': '异常排查', '/tasks': '任务管理', '/datasources': '数据源管理' }[route.path] ?? 'DataWorks Agent'))
const healthTag = ref('checking')
const healthText = ref('检测中...')
onMounted(async () => {
  try {
    const r = await fetch('/api/health')
    if (!r.ok) throw 0
    healthTag.value = 'online'; healthText.value = '服务正常'
  } catch { healthTag.value = 'degraded'; healthText.value = '服务降级' }
})
</script>

<style scoped>
.app-layout { display: flex; min-height: 100vh; background: var(--color-bg-primary); }
.sidebar { position: fixed; top: 0; left: 0; bottom: 0; width: var(--sidebar-width); background: var(--color-bg-secondary); border-right: 1px solid var(--color-border-primary); display: flex; flex-direction: column; z-index: var(--z-sticky); transition: width var(--transition-normal); }
.sidebar-header { padding: var(--space-5); border-bottom: 1px solid var(--color-border-secondary); }
.logo { display: flex; align-items: center; gap: var(--space-4); }
.logo svg { width: 36px; height: 36px; flex-shrink: 0; }
.logo-text { display: flex; flex-direction: column; }
.logo-title { font-size: var(--font-size-md); font-weight: 700; color: var(--color-text-primary); letter-spacing: -0.01em; }
.logo-subtitle { font-size: var(--font-size-xs); color: var(--color-text-tertiary); margin-top: 2px; }
.nav-menu { flex: 1; overflow-y: auto; padding: var(--space-3) var(--space-3); display: flex; flex-direction: column; gap: 4px; }
.nav-item { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); color: var(--color-text-secondary); text-decoration: none; font-size: var(--font-size-sm); font-weight: 500; transition: all var(--transition-fast); cursor: pointer; }
.nav-item:hover { background: var(--color-bg-hover); color: var(--color-text-primary); }
.nav-item.active { background: var(--gradient-subtle); color: var(--color-accent-blue); font-weight: 600; }
.nav-icon { width: 20px; height: 20px; flex-shrink: 0; }
.sidebar-footer { padding: var(--space-4); border-top: 1px solid var(--color-border-secondary); }
.health-status { display: flex; align-items: center; gap: var(--space-2); padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--color-bg-tertiary); font-size: var(--font-size-xs); color: var(--color-text-tertiary); }
.health-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--color-accent-green); box-shadow: 0 0 0 3px rgba(52, 211, 153, 0.2); }
.health-status.checking .health-dot { background: var(--color-accent-orange); box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.2); }
.health-status.degraded .health-dot { background: var(--color-accent-red); box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.2); }
.main-content { flex: 1; margin-left: var(--sidebar-width); display: flex; flex-direction: column; min-height: 100vh; }
.topbar { position: sticky; top: 0; height: var(--topbar-height); display: flex; align-items: center; padding: 0 var(--space-8); border-bottom: 1px solid var(--color-border-primary); z-index: var(--z-sticky); background: var(--color-bg-primary); }
.page-title { font-size: var(--font-size-xl); font-weight: 600; color: var(--color-text-primary); }
.page-content { flex: 1; padding: var(--space-8); overflow-y: auto; }
@media (max-width: 768px) {
  .sidebar { width: var(--sidebar-collapsed-width); }
  .logo-text, .nav-item span { display: none; }
  .nav-item { justify-content: center; padding: var(--space-4); }
  .main-content { margin-left: var(--sidebar-collapsed-width); }
  .topbar { padding: 0 var(--space-4); }
  .page-content { padding: var(--space-4); }
}
</style>
