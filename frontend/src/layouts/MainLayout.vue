<template>
  <el-container class="app-shell">
    <el-aside width="208px" class="app-sidebar">
      <div class="brand">
        <span class="brand-logo">D</span>
        <div><strong>DataWorks Agent</strong><small>智能数仓工作台</small></div>
      </div>

      <nav class="nav-list">
        <span class="nav-caption">工作区</span>
        <router-link to="/" :class="{ active: route.path === '/' }"><el-icon><ChatDotRound /></el-icon><span>Agent 会话</span></router-link>
        <router-link to="/tasks" :class="{ active: route.path.startsWith('/tasks') && !route.path.includes('create') }"><el-icon><List /></el-icon><span>任务运行</span></router-link>
        <router-link to="/artifacts" :class="{ active: route.path.startsWith('/artifacts') }"><el-icon><Document /></el-icon><span>产物中心</span></router-link>

        <template v-if="enableAdvancedTools">
          <span class="nav-caption advanced-caption">高级工具</span>
          <router-link v-for="item in advancedItems" :key="item.path" :to="item.path" :class="{ active: route.path.startsWith(item.path) }">
            <el-icon><component :is="item.icon" /></el-icon><span>{{ item.title }}</span>
          </router-link>
        </template>
      </nav>

      <div class="sidebar-footer">
        <router-link v-if="enableAdvancedTools" to="/settings"><el-icon><Setting /></el-icon><span>设置</span></router-link>
        <div class="workspace-user"><span>DW</span><div><strong>开发工作空间</strong><small>Publish Gate 已启用</small></div></div>
      </div>
    </el-aside>

    <el-container class="content-shell">
      <el-header class="topbar">
        <div><strong>{{ pageTitle }}</strong><span v-if="route.path === '/'">Agent-first</span></div>
        <div class="topbar-right">
          <span class="safety"><i />开发环境</span>
          <span class="health" :class="healthTag"><i />{{ healthText }}</span>
        </div>
      </el-header>
      <el-main class="app-main"><router-view /></el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ChatDotRound, Connection, Document, Grid, List, Setting, Share, Tools, Upload,
} from '@element-plus/icons-vue'

const route = useRoute()
const enableAdvancedTools = import.meta.env.VITE_ENABLE_ADVANCED_TOOLS === 'true'
const advancedItems = [
  { path: '/tasks/create', title: '建模任务', icon: Tools },
  { path: '/di', title: '数据集成', icon: Connection },
  { path: '/datasources', title: '数据源', icon: Grid },
  { path: '/governance', title: '治理中心', icon: Share },
  { path: '/semantic', title: '语义中心', icon: Connection },
  { path: '/import', title: 'SQL 导入', icon: Upload },
]
const pageTitle = computed(() => {
  const map: Record<string, string> = { '/': 'Agent 会话', '/tasks': '任务运行', '/artifacts': '产物中心', '/settings': '设置' }
  return map[route.path] ?? advancedItems.find((item) => route.path.startsWith(item.path))?.title ?? 'DataWorks Agent'
})
const healthTag = ref('checking')
const healthText = ref('正在连接')
onMounted(async () => {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) throw new Error('unhealthy')
    healthTag.value = 'online'; healthText.value = '服务在线'
  } catch { healthTag.value = 'degraded'; healthText.value = '服务降级' }
})
</script>

<style scoped>
.app-shell { min-height: 100vh; background: #f5f5f7; color: #29292f; }
.app-sidebar { position: fixed; inset: 0 auto 0 0; z-index: 10; display: flex; flex-direction: column; padding: 0 12px; border-right: 1px solid #e5e5e8; background: #fff; }
.brand { height: 64px; display: flex; align-items: center; gap: 10px; padding: 0 8px; }.brand-logo { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 9px; background: linear-gradient(145deg,#7658ff,#5034de); color: #fff; font-weight: 800; box-shadow: 0 6px 16px rgba(91,61,226,.2); }.brand strong,.brand small { display: block; }.brand strong { color: #25252b; font-size: 13px; }.brand small { margin-top: 2px; color: #a0a0a7; font-size: 9px; }
.nav-list { display: flex; flex-direction: column; gap: 3px; margin-top: 12px; }.nav-caption { padding: 10px 10px 5px; color: #aaaab0; font-size: 9px; font-weight: 800; letter-spacing: .1em; }.advanced-caption { margin-top: 15px; }.nav-list a,.sidebar-footer>a { height: 38px; display: flex; align-items: center; gap: 10px; padding: 0 10px; border-radius: 8px; color: #696970; font-size: 12px; text-decoration: none; transition: .16s; }.nav-list a:hover,.sidebar-footer>a:hover { background: #f3f3f5; color: #2f2f35; }.nav-list a.active { background: #eeebff; color: #6243ec; font-weight: 700; }.nav-list .el-icon { font-size: 16px; }
.sidebar-footer { margin-top: auto; padding-bottom: 12px; }.workspace-user { display: flex; align-items: center; gap: 9px; margin-top: 8px; padding: 10px 8px; border-top: 1px solid #ededf0; }.workspace-user>span { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 8px; background: #242429; color: #fff; font-size: 9px; font-weight: 800; }.workspace-user strong,.workspace-user small { display: block; }.workspace-user strong { color: #4c4c53; font-size: 10px; }.workspace-user small { margin-top: 2px; color: #aaaab0; font-size: 8px; }
.content-shell { min-width: 0; margin-left: 208px; }.topbar { height: 54px; display: flex; align-items: center; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid #e5e5e8; background: rgba(255,255,255,.92); backdrop-filter: blur(12px); }.topbar>div:first-child { display: flex; align-items: center; gap: 8px; }.topbar strong { font-size: 13px; }.topbar>div:first-child span { padding: 3px 6px; border-radius: 5px; background: #eeebff; color: #6748ef; font-size: 9px; font-weight: 700; }.topbar-right { display: flex; align-items: center; gap: 8px; }.topbar-right>span { display: flex; align-items: center; gap: 5px; color: #818188; font-size: 10px; }.topbar-right i { width: 6px; height: 6px; border-radius: 50%; background: #20b26b; }.health.checking i { background: #e6a23c; }.health.degraded i { background: #e05656; }
.app-main { min-width: 0; padding: 6px; overflow: hidden; background: #f5f5f7; }
@media(max-width:760px){.app-sidebar{display:none}.content-shell{margin-left:0}.topbar{padding:0 12px}.app-main{padding:0}.safety{display:none!important}}
</style>
