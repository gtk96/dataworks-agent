<template>
  <div v-loading="loading">
    <el-tabs v-model="tab">
      <el-tab-pane label="SQL 血缘" name="sql">
        <el-input v-model="sqlText" type="textarea" :rows="8" placeholder="粘贴 INSERT SELECT SQL" />
        <span v-if="sqlText.trim()" style="display:block;margin-top:6px;color:#999;font-size:12px">内容变化后自动解析</span>
      </el-tab-pane>

      <el-tab-pane label="DDL 规范检查" name="ddl">
        <el-input v-model="ddlText" type="textarea" :rows="8" placeholder="粘贴 CREATE TABLE DDL" />
        <el-button type="primary" style="margin-top:8px" @click="checkDdl" :loading="ddlChecking">检查 DDL</el-button>
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

      <el-tab-pane label="上游追溯" name="lineage">
        <el-form inline>
          <el-form-item label="表名"><el-input v-model="lineageTable" style="width:240px" clearable /></el-form-item>
          <el-form-item label="MC 项目">
            <el-select v-model="lineageProject" style="width:160px" clearable placeholder="选择项目" filterable allow-create>
              <el-option value="dataworks" label="dataworks (prod)" />
              <el-option value="dataworks_dev" label="dataworks_dev (dev)" />
              <el-option value="dataworks_aliyun" label="dataworks_aliyun" />
              <el-option value="dataworks_develop" label="dataworks_develop" />
              <el-option value="cda_dev" label="cda_dev" />
            </el-select>
          </el-form-item>
          <el-form-item label="环境">
            <el-select v-model="lineageEnv" style="width:100px">
              <el-option value="prod" label="prod" />
              <el-option value="dev" label="dev" />
            </el-select>
          </el-form-item>
          <el-button type="success" @click="exportLineage" :loading="exporting">导出 ZIP</el-button>
        </el-form>
        <el-input
          v-model="excludedIds"
          placeholder="排除 node_id，逗号分隔（可选）"
          style="width:100%;margin-top:8px"
        />
        <span v-if="lineageTable" style="display:block;margin-top:6px;color:#999;font-size:12px">表名填写后自动预览</span>
      </el-tab-pane>

      <el-tab-pane label="词根字典" name="roots">
        <el-input v-model="rootQuery" placeholder="搜索词根（留空显示常用）" style="width:320px" clearable />
      </el-tab-pane>

      <el-tab-pane label="血缘 DAG" name="graph">
        <el-input v-model="lineageTable" placeholder="表名" style="width:320px" clearable />
        <el-input-number v-model="graphDepth" :min="1" :max="10" style="margin-left:8px" />
        <span style="margin-left:8px;color:#999">深度</span>
      </el-tab-pane>

      <el-tab-pane label="下游影响" name="downstream">
        <el-input v-model="lineageTable" placeholder="表名" style="width:320px" clearable />
      </el-tab-pane>

      <el-tab-pane label="表名解析" name="parse-table">
        <el-input v-model="parseTableName" placeholder="输入表名 (e.g. dwd_ord_s_order_hour)" style="width:380px" clearable />
      </el-tab-pane>

      <el-tab-pane label="更新方式推断" name="infer-mode">
        <el-input v-model="parseTableName" placeholder="输入表名" style="width:380px" clearable />
      </el-tab-pane>

      <el-tab-pane label="分层规范" name="conventions">
        <el-select v-model="conventionLayer" style="width:200px">
          <el-option value="ODS" label="ODS" />
          <el-option value="DWD" label="DWD" />
          <el-option value="DIM" label="DIM" />
          <el-option value="DWS" label="DWS" />
          <el-option value="DMR" label="DMR" />
        </el-select>
      </el-tab-pane>

      <el-tab-pane label="字段词根校验" name="check-fields">
        <el-input v-model="fieldsRaw" type="textarea" :rows="6" placeholder="每行一个字段名,如:
order_id
order_amt
cust_nm" />
      </el-tab-pane>
    </el-tabs>

    <el-alert v-if="error" type="error" :title="error" :closable="false" style="margin-top:16px" />
    <CodeBlock v-if="resultText" style="margin-top:12px">{{ resultText }}</CodeBlock>
    <el-empty v-else-if="!loading && !error" description="切换 Tab 或修改选项后将自动加载" style="margin-top:24px" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { request } from '@/utils/request'
import CodeBlock from '@/components/CodeBlock.vue'

const tab = ref('sql')
const sqlText = ref('')
const ddlText = ref('')
const ddlResult = ref<{ passed: boolean; errors: string[]; warnings: string[] } | null>(null)
const ddlChecking = ref(false)
const lineageTable = ref('')
const lineageProject = ref('')
const lineageEnv = ref('prod')
const excludedIds = ref('')
const rootQuery = ref('')
const parseTableName = ref('')
const graphDepth = ref(3)
const conventionLayer = ref('DWD')
const fieldsRaw = ref('')
const loading = ref(false)
const exporting = ref(false)
const error = ref('')
const resultText = ref('')

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
  if (!lineageTable.value.trim()) return
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
    if (downloadUrl) {
      window.open(downloadUrl, '_blank')
    }
  } catch (e: any) {
    error.value = e.message
  }
  exporting.value = false
}

async function searchRoots() {
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const q = encodeURIComponent(rootQuery.value)
    const r = await request<Record<string, unknown>>(`/api/governance/word-roots?q=${q}&limit=100`)
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function loadGraph() {
  if (!lineageTable.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>(`/api/lineage/graph/${encodeURIComponent(lineageTable.value.trim())}?max_depth=${graphDepth.value}`)
    resultText.value = JSON.stringify(r, null, 2)
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
    const r = await request<Record<string, unknown>>(`/api/lineage/downstream/${encodeURIComponent(lineageTable.value.trim())}`)
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function parseTable() {
  if (!parseTableName.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>('/api/governance/parse-table-name', {
      method: 'POST',
      body: { table_name: parseTableName.value.trim() },
    })
    resultText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}

async function inferMode() {
  if (!parseTableName.value.trim()) return
  loading.value = true
  error.value = ''
  resultText.value = ''
  try {
    const r = await request<Record<string, unknown>>('/api/governance/infer-update-mode', {
      method: 'POST',
      body: { table_name: parseTableName.value.trim() },
    })
    resultText.value = JSON.stringify(r, null, 2)
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
    const fields = fieldsRaw.value.split(/[\n,]+/).map(s => s.trim()).filter(Boolean)
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

function runTabLoader(name: string) {
  error.value = ''
  resultText.value = ''
  if (name === 'sql' && sqlText.value.trim()) parseSql()
  else if (name === 'lineage' && lineageTable.value.trim()) previewLineage()
  else if (name === 'roots') searchRoots()
  else if (name === 'graph' && lineageTable.value.trim()) loadGraph()
  else if (name === 'downstream' && lineageTable.value.trim()) loadDownstream()
  else if (name === 'parse-table' && parseTableName.value.trim()) parseTable()
  else if (name === 'infer-mode' && parseTableName.value.trim()) inferMode()
  else if (name === 'conventions') loadConventions()
  else if (name === 'check-fields' && fieldsRaw.value.trim()) checkFields()
}

watch(tab, (name) => runTabLoader(name))

watch(sqlText, () => {
  if (tab.value === 'sql') delayInvoke(parseSql, 600)
})

watch([lineageTable, lineageProject, lineageEnv], () => {
  if (tab.value === 'lineage') delayInvoke(previewLineage, 500)
  else if (tab.value === 'graph') delayInvoke(loadGraph, 500)
  else if (tab.value === 'downstream') delayInvoke(loadDownstream, 500)
})

watch(rootQuery, () => {
  if (tab.value === 'roots') delayInvoke(searchRoots, 300)
})

watch(graphDepth, () => {
  if (tab.value === 'graph' && lineageTable.value.trim()) delayInvoke(loadGraph, 300)
})

watch(conventionLayer, () => {
  if (tab.value === 'conventions') delayInvoke(loadConventions, 200)
})

watch(fieldsRaw, () => {
  if (tab.value === 'check-fields') delayInvoke(checkFields, 500)
})
</script>
