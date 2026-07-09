<template>
  <div v-loading="loading">
    <el-alert
      v-if="depWarning"
      type="warning"
      :title="depWarning"
      :closable="false"
      show-icon
      style="margin-bottom:12px"
    />

    <el-tabs v-model="tab">
      <!-- 规范检查：DDL + 字段词根 -->
      <el-tab-pane label="规范检查" name="check">
        <el-tabs v-model="checkMode" type="card" style="margin-top:4px">
          <el-tab-pane label="DDL 检查" name="ddl">
            <el-input
              v-model="ddlText"
              type="textarea"
              :rows="8"
              placeholder="粘贴 CREATE TABLE DDL（词根优先 MCP 线上表；可先同步最新词根）"
            />
            <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
              <el-button type="primary" @click="checkDdl" :loading="ddlChecking">检查 DDL</el-button>
              <el-button @click="syncWordRoots" :loading="rootSyncing">获取最新词根</el-button>
              <span v-if="rootSyncedAt" style="color:#999;font-size:12px">
                词根已同步 {{ rootSyncedAt }}（{{ rootTotal }} 条）
              </span>
            </div>
            <div v-if="ddlResult" style="margin-top:12px">
              <el-alert :type="ddlResult.passed ? 'success' : 'warning'" :closable="false" show-icon>
                <template #title>{{ ddlResult.passed ? 'DDL 规范检查通过' : 'DDL 规范检查未通过' }}</template>
                <template #default>
                  <div v-if="ddlResult.errors.length" style="margin-top:8px">
                    <div v-for="e in ddlResult.errors" :key="e" style="color:#F56C6C">❌ {{ e }}</div>
                  </div>
                  <div v-if="ddlResult.warnings.length" style="margin-top:8px">
                    <div v-for="w in ddlResult.warnings" :key="w" style="color:#E6A23C">⚠️ {{ w }}</div>
                  </div>
                </template>
              </el-alert>
            </div>
          </el-tab-pane>
          <el-tab-pane label="字段词根" name="fields">
            <el-input
              v-model="fieldsRaw"
              type="textarea"
              :rows="6"
              placeholder="每行一个字段名，如: order_id / order_amt / cust_nm"
            />
            <span v-if="fieldsRaw.trim()" style="display:block;margin-top:6px;color:#999;font-size:12px">
              内容变化后自动校验
            </span>
          </el-tab-pane>
        </el-tabs>
      </el-tab-pane>

      <!-- 词根字典 -->
      <el-tab-pane label="词根字典" name="roots">
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap">
          <el-input v-model="rootQuery" placeholder="搜索词根（留空显示常用）" style="width:320px" clearable />
          <el-button type="primary" @click="syncWordRoots" :loading="rootSyncing">获取最新词根</el-button>
        </div>
        <span v-if="rootSyncedAt" style="display:block;margin-bottom:8px;color:#999;font-size:12px">
          来源：{{ rootSource === 'online' ? '线上词根表' : '内置字典' }} · 同步于 {{ rootSyncedAt }} · 共 {{ rootTotal }} 条
          <span v-if="rootAutoSyncLabel"> · 自动同步 {{ rootAutoSyncLabel }}</span>
        </span>
      </el-tab-pane>

      <!-- 表血缘：预览 / DAG / 下游 / SQL -->
      <el-tab-pane label="表血缘" name="lineage">
        <el-form inline style="margin-bottom:8px">
          <el-form-item label="表名">
            <el-input v-model="lineageTable" style="width:240px" clearable placeholder="dwd_xxx_day" />
          </el-form-item>
          <el-form-item label="MC 项目">
            <el-select
              v-model="lineageProject"
              style="width:160px"
              clearable
              placeholder="自动解析"
              filterable
              allow-create
            >
              <el-option v-for="p in mcProjectOptions" :key="p.value" :value="p.value" :label="p.label" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="lineageView === 'preview'" label="环境">
            <el-select v-model="lineageEnv" style="width:100px">
              <el-option value="prod" label="prod" />
              <el-option value="dev" label="dev" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="lineageView === 'graph'" label="深度">
            <el-input-number v-model="graphDepth" :min="1" :max="10" />
          </el-form-item>
        </el-form>

        <el-radio-group v-model="lineageView" style="margin-bottom:12px">
          <el-radio-button value="graph">上游 DAG</el-radio-button>
          <el-radio-button value="downstream">下游影响</el-radio-button>
          <el-radio-button value="preview">节点追溯</el-radio-button>
          <el-radio-button value="sql">SQL 解析</el-radio-button>
        </el-radio-group>

        <el-alert
          v-if="lineageView === 'preview'"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom:8px"
        >
          <template #title>
            节点追溯 / 导出 ZIP 需调度节点权限（L3）；DAG / 下游为表级血缘（L2）。MC 项目留空时自动搜索 prod schema。
          </template>
        </el-alert>

        <template v-if="lineageView === 'preview'">
          <el-input
            v-model="excludedIds"
            placeholder="排除 node_id，逗号分隔（可选）"
            style="width:100%;margin-bottom:8px"
          />
          <el-button
            type="success"
            @click="exportLineage"
            :loading="exporting"
            :disabled="!nodeLineageReady"
          >
            导出 ZIP
          </el-button>
          <span v-if="!nodeLineageReady" style="margin-left:8px;color:#E6A23C;font-size:12px">
            Cookie 未就绪，节点追溯不可用
          </span>
          <span v-else-if="lineageTable" style="display:block;margin-top:6px;color:#999;font-size:12px">
            表名填写后自动预览
          </span>
        </template>

        <template v-else-if="lineageView === 'sql'">
          <el-input v-model="sqlText" type="textarea" :rows="8" placeholder="粘贴 INSERT SELECT SQL" />
          <span v-if="sqlText.trim()" style="display:block;margin-top:6px;color:#999;font-size:12px">
            内容变化后自动解析
          </span>
        </template>

        <span
          v-else-if="lineageTable && lineageView !== 'sql'"
          style="display:block;margin-top:4px;color:#999;font-size:12px"
        >
          表名填写后自动查询
        </span>
      </el-tab-pane>

      <!-- 规范参考 -->
      <el-tab-pane label="规范参考" name="reference">
        <el-form inline style="margin-bottom:12px">
          <el-form-item label="分层">
            <el-select v-model="conventionLayer" style="width:200px">
              <el-option value="ODS" label="ODS" />
              <el-option value="DWD" label="DWD" />
              <el-option value="DIM" label="DIM" />
              <el-option value="DWS" label="DWS" />
              <el-option value="DMR" label="DMR" />
            </el-select>
          </el-form-item>
        </el-form>
        <el-collapse v-model="referencePanels">
          <el-collapse-item title="命名工具（表名解析 + 更新方式推断）" name="naming">
            <el-input
              v-model="parseTableName"
              placeholder="输入表名，如 dwd_ord_s_order_hour"
              style="width:380px;margin-bottom:8px"
              clearable
            />
            <el-button type="primary" :disabled="!parseTableName.trim()" @click="runNamingTools">
              解析
            </el-button>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>
    </el-tabs>

    <el-alert v-if="error" type="error" :title="error" :closable="false" style="margin-top:16px" />
    <CodeBlock v-if="resultText" style="margin-top:12px">{{ resultText }}</CodeBlock>
    <el-empty
      v-else-if="!loading && !error && showEmptyHint"
      description="填写内容或切换视图后将自动加载"
      style="margin-top:24px"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'
import CodeBlock from '@/components/CodeBlock.vue'

const tab = ref('check')
const checkMode = ref('ddl')
const lineageView = ref('graph')
const sqlText = ref('')
const ddlText = ref('')
const ddlResult = ref<{ passed: boolean; errors: string[]; warnings: string[] } | null>(null)
const ddlChecking = ref(false)
const lineageTable = ref('')
const lineageProject = ref('')
const lineageEnv = ref('prod')
const excludedIds = ref('')
const rootQuery = ref('')
const rootSyncing = ref(false)
const rootSyncedAt = ref('')
const rootTotal = ref(0)
const rootSource = ref('bundled')
const rootAutoSyncLabel = ref('')
const parseTableName = ref('')
const graphDepth = ref(3)
const conventionLayer = ref('DWD')
const fieldsRaw = ref('')
const referencePanels = ref<string[]>([])
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const resultText = ref('')
const depWarning = ref('')
const nodeLineageReady = ref(true)
const mcProjectOptions = ref<{ value: string; label: string }[]>([])

const showEmptyHint = computed(() => {
  if (tab.value === 'check') {
    return checkMode.value === 'fields' ? !fieldsRaw.value.trim() : !ddlResult.value
  }
  if (tab.value === 'roots') return !rootQuery.value.trim()
  if (tab.value === 'lineage') {
    if (lineageView.value === 'sql') return !sqlText.value.trim()
    return !lineageTable.value.trim()
  }
  if (tab.value === 'reference') return !parseTableName.value.trim()
  return true
})

function lineageQuerySuffix(): string {
  const params = new URLSearchParams()
  if (lineageProject.value.trim()) params.set('mc_project', lineageProject.value.trim())
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

async function loadRuntimeHints() {
  try {
    const hints = await request<Record<string, unknown>>('/api/governance/runtime-hints')
    const prod = String(hints.mc_prod_project || 'dataworks')
    const dev = String(hints.mc_dev_project || 'dataworks_dev')
    mcProjectOptions.value = [
      { value: '', label: '自动解析（推荐）' },
      { value: prod, label: `${prod} (prod)` },
      { value: dev, label: `${dev} (dev)` },
      { value: 'dataworks', label: 'dataworks' },
      { value: 'dataworks_dev', label: 'dataworks_dev' },
    ]
    nodeLineageReady.value = Boolean(hints.bff_available)
    const parts: string[] = []
    if (!hints.bff_available) parts.push('BFF/Cookie 未就绪')
    if (!hints.mcp_available) parts.push('MCP 不可用（词根线上校验会降级为内置字典）')
    if (parts.length) {
      depWarning.value = `${parts.join('；')}。请在系统设置更新 Cookie 或 MCP Token。`
    }
  } catch {
    /* ignore */
  }
}

async function loadHealthBanner() {
  try {
    const h = await request<{ status?: string; checks?: Record<string, unknown> }>('/api/health')
    if (h.checks?.cookie_health === 'degraded' || h.checks?.cookie === 'degraded') {
      nodeLineageReady.value = false
    }
    if (h.status === 'degraded' && !depWarning.value) {
      const checks = h.checks || {}
      const bits: string[] = []
      if (checks.mcp === 'degraded') bits.push('MCP 认证失效')
      if (checks.cookie_health === 'degraded') bits.push('Cookie 即将过期或无效')
      depWarning.value = bits.length
        ? `${bits.join('、')}，表级血缘可能为空、节点追溯不可用。`
        : '服务处于降级状态，部分治理/血缘能力可能不可用。'
    }
  } catch {
    /* ignore */
  }
}

function delayInvoke(fn: () => void, ms = 400) {
  setTimeout(fn, ms)
}

async function parseSql() {
  if (!sqlText.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>('/api/governance/parse-sql-lineage', {
      method: 'POST',
      body: { sql: sqlText.value },
    })
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function checkDdl() {
  if (!ddlText.value.trim()) return
  ddlChecking.value = true
  ddlResult.value = null
  try {
    ddlResult.value = await request('/api/governance/check-ddl', {
      method: 'POST',
      body: { ddl: ddlText.value },
    })
  } catch (e: any) {
    error.value = e.message
  }
  ddlChecking.value = false
}

async function previewLineage() {
  if (!lineageTable.value.trim() || !nodeLineageReady.value) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>('/api/governance/lineage/preview', {
      method: 'POST',
      body: {
        table_name: lineageTable.value.trim(),
        mc_project: lineageProject.value,
        env: lineageEnv.value,
      },
    })
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function exportLineage() {
  if (!lineageTable.value.trim()) {
    error.value = '请先填写表名'
    return
  }
  if (!nodeLineageReady.value) {
    ElMessage.warning('Cookie 未就绪，无法导出节点代码')
    return
  }
  exporting.value = true
  error.value = ''
  resultText.value = ''
  try {
    const excluded = excludedIds.value
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const r = await request<Record<string, unknown>>('/api/governance/lineage/export', {
      method: 'POST',
      body: {
        table_name: lineageTable.value.trim(),
        mc_project: lineageProject.value,
        env: lineageEnv.value,
        excluded_node_ids: excluded,
      },
    })
    resultText.value = JSON.stringify(r, null, 2)
    const downloadUrl = r.download_url as string | undefined
    if (downloadUrl) window.open(downloadUrl, '_blank')
  } catch (e: any) {
    error.value = e.message
  }
  exporting.value = false
}

async function loadWordRootSyncStatus() {
  try {
    const r = await request<Record<string, unknown>>('/api/governance/word-roots/sync-status')
    if (r.synced_at) rootSyncedAt.value = String(r.synced_at)
    if (r.total) rootTotal.value = Number(r.total)
    if (r.source) rootSource.value = String(r.source)
    rootAutoSyncLabel.value = r.auto_sync_enabled
      ? String(r.interval_label || `每 ${Number(r.interval_seconds || 7200) / 3600} 小时`)
      : '已关闭'
  } catch {
    /* ignore */
  }
}

async function searchRoots() {
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const q = encodeURIComponent(rootQuery.value)
    const r = await request<Record<string, unknown>>(`/api/governance/word-roots?q=${q}&limit=100`)
    rootSyncedAt.value = String(r.synced_at || '')
    rootTotal.value = Number(r.total || 0)
    rootSource.value = String(r.source || 'bundled')
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function syncWordRoots() {
  rootSyncing.value = true
  error.value = ''
  try {
    const r = await request<Record<string, unknown>>('/api/governance/word-roots/sync', { method: 'POST' })
    rootSyncedAt.value = String(r.refreshed_at || r.synced_at || '')
    rootTotal.value = Number(r.count || r.total || 0)
    rootSource.value = String(r.source || 'online')
    ElMessage.success(`词根已同步：${rootTotal.value} 条`)
    if (tab.value === 'roots') await searchRoots()
  } catch (e: any) {
    ElMessage.error(e.message || '词根同步失败')
    error.value = e.message
  }
  rootSyncing.value = false
}

async function loadGraph() {
  if (!lineageTable.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const depth = `max_depth=${graphDepth.value}`
    const qs = lineageQuerySuffix()
    const sep = qs ? `${qs}&` : '?'
    const r = await request<Record<string, unknown>>(
      `/api/lineage/graph/${encodeURIComponent(lineageTable.value.trim())}${sep}${depth}`
    )
    resultText.value = JSON.stringify(r, null, 2)
    if (!Array.isArray(r.nodes) || (r.nodes as unknown[]).length === 0) {
      ElMessage.warning(String(r.note || '未查到上游血缘，请确认表名或 MC 项目'))
    }
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function loadDownstream() {
  if (!lineageTable.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>(
      `/api/lineage/downstream/${encodeURIComponent(lineageTable.value.trim())}${lineageQuerySuffix()}`
    )
    resultText.value = JSON.stringify(r, null, 2)
    if (!Array.isArray(r.downstream) || (r.downstream as unknown[]).length === 0) {
      ElMessage.warning(String(r.note || '未查到下游影响'))
    }
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function runNamingTools() {
  if (!parseTableName.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const name = parseTableName.value.trim()
    const [parsed, mode] = await Promise.all([
      request<Record<string, unknown>>('/api/governance/parse-table-name', {
        method: 'POST',
        body: { table_name: name },
      }),
      request<Record<string, unknown>>('/api/governance/infer-update-mode', {
        method: 'POST',
        body: { table_name: name },
      }),
    ])
    resultText.value = JSON.stringify({ parse: parsed, update_mode: mode }, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function loadConventions() {
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>(`/api/governance/conventions/${conventionLayer.value}`)
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function checkFields() {
  if (!fieldsRaw.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const fields = fieldsRaw.value.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean)
    const r = await request<Record<string, unknown>>('/api/roots/check', {
      method: 'POST',
      body: { fields },
    })
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

function runLineageLoader() {
  error.value = ''
  resultText.value = ''
  if (lineageView.value === 'preview') delayInvoke(previewLineage, 500)
  else if (lineageView.value === 'graph') delayInvoke(loadGraph, 500)
  else if (lineageView.value === 'downstream') delayInvoke(loadDownstream, 500)
  else if (lineageView.value === 'sql' && sqlText.value.trim()) delayInvoke(parseSql, 600)
}

function runTabLoader(name: string) {
  error.value = ''
  resultText.value = ''
  if (name === 'check') {
    if (checkMode.value === 'fields' && fieldsRaw.value.trim()) checkFields()
  } else if (name === 'roots') {
    loadWordRootSyncStatus()
    searchRoots()
  } else if (name === 'lineage' && lineageTable.value.trim()) {
    runLineageLoader()
  } else if (name === 'reference') {
    loadConventions()
  }
}

watch(tab, (name) => runTabLoader(name))

watch(checkMode, (mode) => {
  if (tab.value === 'check' && mode === 'fields' && fieldsRaw.value.trim()) {
    delayInvoke(checkFields, 300)
  }
})

watch(lineageView, () => {
  if (tab.value === 'lineage') runLineageLoader()
})

watch(sqlText, () => {
  if (tab.value === 'lineage' && lineageView.value === 'sql') delayInvoke(parseSql, 600)
})

watch([lineageTable, lineageProject, lineageEnv], () => {
  if (tab.value !== 'lineage') return
  if (lineageView.value === 'preview') delayInvoke(previewLineage, 500)
  else if (lineageView.value === 'graph') delayInvoke(loadGraph, 500)
  else if (lineageView.value === 'downstream') delayInvoke(loadDownstream, 500)
})

watch(rootQuery, () => {
  if (tab.value === 'roots') delayInvoke(searchRoots, 300)
})

watch(graphDepth, () => {
  if (tab.value === 'lineage' && lineageView.value === 'graph' && lineageTable.value.trim()) {
    delayInvoke(loadGraph, 300)
  }
})

watch(conventionLayer, () => {
  if (tab.value === 'reference') delayInvoke(loadConventions, 200)
})

watch(fieldsRaw, () => {
  if (tab.value === 'check' && checkMode.value === 'fields') delayInvoke(checkFields, 500)
})

onMounted(async () => {
  await Promise.all([loadRuntimeHints(), loadHealthBanner(), loadWordRootSyncStatus()])
})
</script>
