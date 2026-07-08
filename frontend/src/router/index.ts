import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: [
        { path: '', name: 'Dashboard', component: () => import('@/pages/ModelingDashboard.vue') },
        { path: 'tasks', name: 'TaskList', component: () => import('@/pages/TaskList.vue') },
        { path: 'tasks/create', name: 'TaskCreate', component: () => import('@/pages/ModelingWorkbench.vue') },
        { path: 'tasks/:id', name: 'TaskDetail', component: () => import('@/pages/TaskDetail.vue') },
        { path: 'sync', name: 'SyncManager', component: () => import('@/pages/SyncManager.vue') },
        { path: 'reconciliation', name: 'Reconciliation', component: () => import('@/pages/ReconciliationView.vue') },
        { path: 'ownership', name: 'Ownership', component: () => import('@/pages/OwnershipView.vue') },
        { path: 'bus-matrix', name: 'BusMatrix', component: () => import('@/pages/BusMatrixView.vue') },
        { path: 'artifacts', name: 'Artifacts', component: () => import('@/pages/ArtifactsView.vue') },
        { path: 'di', name: 'DataIntegration', component: () => import('@/pages/DataIntegration.vue') },
        { path: 'datasources', name: 'DataSourceManager', component: () => import('@/pages/DataSourceManager.vue') },
        { path: 'governance', name: 'GovernanceHub', component: () => import('@/pages/GovernanceHub.vue') },
        { path: 'semantic', name: 'SemanticHub', component: () => import('@/pages/SemanticHub.vue') },
        { path: 'import', name: 'ImportSql', component: () => import('@/pages/ImportSql.vue') },
        { path: 'settings', name: 'Settings', component: () => import('@/pages/Settings.vue') },
        { path: 'dwd', name: 'DwdWorkbench', component: () => import('@/pages/DwdWorkbench.vue') },
        { path: 'pipeline', name: 'PipelineHub', component: () => import('@/pages/PipelineHub.vue') },
        { path: 'tasks/create-wizard', name: 'TaskCreateWizard', component: () => import('@/pages/TaskCreateWizard.vue') },
      ],
    },
  ],
})

export default router
