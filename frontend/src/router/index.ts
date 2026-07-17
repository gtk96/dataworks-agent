import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const coreChildren = [
  { path: '', name: 'Dashboard', component: () => import('@/pages/SmartChatPage.vue') },
  { path: 'anomaly', name: 'AnomalyDetection', component: () => import('@/pages/AnomalyDetection.vue') },
  { path: 'tasks', name: 'TaskList', component: () => import('@/pages/TaskList.vue') },
  { path: 'tasks/:id', name: 'TaskDetail', component: () => import('@/pages/TaskDetail.vue') },
  { path: 'datasources', name: 'DataSourceManager', component: () => import('@/pages/DataSourceManager.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      children: coreChildren,
    },
  ],
})

export default router
