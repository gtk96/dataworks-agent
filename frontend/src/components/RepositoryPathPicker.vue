<template>
  <div class="repo-path-picker">
    <div class="toolbar">
      <span class="label">{{ label }}</span>
      <el-tag type="primary" effect="plain">{{ modelValue || '未选择' }}</el-tag>
      <el-button size="small" @click="toggleTree">{{ showTree ? '收起' : '浏览目录' }}</el-button>
      <el-button
        v-for="preset in props.presets"
        :key="preset"
        size="small"
        link
        type="primary"
        @click="selectPath(preset)"
      >
        {{ preset.split('/').slice(-1)[0] || preset }}
      </el-button>
    </div>
    <div v-if="showTree" class="tree-panel">
      <div class="tree-toolbar">
        <span v-if="treePath">当前: {{ treePath }}</span>
        <span v-else>从 DataWorks IDE 根目录浏览</span>
        <el-button v-if="treePath" size="small" @click="loadTree(parentPath(treePath))">上一级</el-button>
        <el-button size="small" type="primary" @click="selectPath(treePath || props.rootPath)">选此目录</el-button>
      </div>
      <div
        v-for="node in treeNodes"
        :key="node.uuid || node.path"
        class="tree-node"
        @click="node.type === 'folder' ? loadTree(node.path) : null"
      >
        <span>{{ node.type === 'folder' ? '📁' : '📄' }}</span>
        <span class="node-name">{{ node.name }}</span>
      </div>
      <div v-if="treeLoading" class="hint">加载中...</div>
      <div v-if="!treeLoading && treeNodes.length === 0" class="hint">无子节点</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { request } from '@/utils/request'

const modelValue = defineModel<string>({ default: 'dataworks_agent/01_ODS' })

const props = withDefaults(
  defineProps<{
    label?: string
    rootPath?: string
    presets?: string[]
  }>(),
  {
    label: '节点目录',
    rootPath: 'dataworks_agent',
    presets: () => ['dataworks_agent/01_ODS', 'dataworks_agent/02_DWD', 'dataworks_agent'],
  },
)

const showTree = ref(false)
const treePath = ref('')
const treeNodes = ref<any[]>([])
const treeLoading = ref(false)

async function loadTree(path: string = '') {
  treeLoading.value = true
  treePath.value = path
  try {
    const r = await request<{ nodes: any[] }>(`/api/workspace/repository-tree?path=${encodeURIComponent(path)}`)
    treeNodes.value = r.nodes || []
  } catch {
    treeNodes.value = []
  }
  treeLoading.value = false
}

function parentPath(path: string): string {
  const parts = path.split('/')
  parts.pop()
  return parts.join('/')
}

function selectPath(path: string) {
  if (!path) return
  modelValue.value = path.replace(/\/+$/, '')
  showTree.value = false
}

function toggleTree() {
  showTree.value = !showTree.value
}

watch(showTree, async (visible) => {
  if (visible) await loadTree(modelValue.value || props.rootPath)
})
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.label {
  color: #606266;
  font-size: 14px;
}
.tree-panel {
  margin-top: 12px;
  border: 1px solid #eee;
  padding: 12px;
  max-height: 300px;
  overflow-y: auto;
  border-radius: 4px;
}
.tree-toolbar {
  margin-bottom: 8px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.tree-node {
  padding: 6px 0;
  cursor: pointer;
  border-bottom: 1px solid #f5f5f5;
}
.node-name {
  margin-left: 4px;
}
.hint {
  color: #999;
}
</style>
