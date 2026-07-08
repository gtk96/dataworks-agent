<template>
  <div>
    <el-tabs v-model="activeTab">
      <!-- 外部数据源 -->
      <el-tab-pane label="外部数据源" name="external">
        <el-row :gutter="16">
          <el-col :span="8">
            <el-card header="数据源列表" style="height:500px;overflow:auto">
              <el-input v-model="dsKeyword" placeholder="搜索数据源" clearable style="margin-bottom:12px" @input="debouncedLoadDS" />
              <el-select v-model="dsTypeFilter" placeholder="按类型" clearable style="width:100%;margin-bottom:12px" @change="loadDataSources">
                <el-option value="" label="全部" />
                <el-option value="mysql" label="MySQL" />
                <el-option value="polardb" label="PolarDB" />
                <el-option value="hologres" label="Hologres" />
                <el-option value="postgresql" label="PostgreSQL" />
                <el-option value="mongodb" label="MongoDB" />
                <el-option value="oss" label="OSS" />
                <el-option value="kafka" label="Kafka" />
                <el-option value="elasticsearch" label="Elasticsearch" />
              </el-select>
              <div v-for="ds in dataSources" :key="ds.name"
                   :class="['ds-item', selectedDS === ds.name && 'active']"
                   @click="selectDS(ds)">
                <div style="font-weight:500">{{ ds.name }}</div>
                <el-tag size="small" type="info">{{ ds.type_label }}</el-tag>
              </div>
              <div v-if="!dataSources.length" style="color:#999;text-align:center;padding:20px">暂无数据源</div>
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card :header="selectedDS ? `${selectedDS} 的表 (${dsTables.length})` : '表列表'" style="height:500px;overflow:auto">
              <el-input v-model="tableFilter" placeholder="过滤表名" clearable style="margin-bottom:12px" />
              <div v-for="t in filteredTables" :key="t.name"
                   :class="['table-item', selectedTable === t.name && 'active']"
                   @click="selectTable(t.name)">
                {{ t.name }}
              </div>
              <div v-if="!dsTables.length && selectedDS" style="color:#999;text-align:center;padding:20px">暂无表</div>
              <div v-if="!selectedDS" style="color:#999;text-align:center;padding:20px">← 请先选择数据源</div>
            </el-card>
          </el-col>
          <el-col :span="8">
            <el-card :header="selectedTable ? `${selectedTable} 字段` : '字段预览'" style="height:500px;overflow:auto">
              <el-alert
                v-if="selectedTable"
                title="外部数据源暂不支持在线字段预览，仅展示表名"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom:12px"
              />
              <div v-if="selectedTable" style="color:#999;text-align:center;padding:20px">暂无字段数据（仅展示表名）</div>
              <div v-else style="color:#999;text-align:center;padding:20px">← 请先选择表</div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- Holo 数据源 -->
      <el-tab-pane label="Holo 数据源" name="holo">
        <el-row :gutter="16">
          <el-col :span="6">
            <el-card header="Holo Schema" style="height:500px;overflow:auto">
              <div v-for="s in holoSchemas" :key="s"
                   :class="['ds-item', selectedHoloSchema === s && 'active']"
                   @click="loadHoloTables(s)">
                {{ s }}
              </div>
            </el-card>
          </el-col>
          <el-col :span="6">
            <el-card :header="selectedHoloSchema ? `${selectedHoloSchema} 的表` : '表列表'" style="height:500px;overflow:auto">
              <el-input v-model="holoTableFilter" placeholder="过滤表名" clearable style="margin-bottom:12px" />
              <div v-for="t in filteredHoloTables" :key="t.name"
                   :class="['table-item', selectedHoloTable === t.name && 'active']"
                   @click="loadHoloColumns(t.name)">
                {{ t.name }}
              </div>
              <div v-if="!holoTables.length && selectedHoloSchema" style="color:#999;text-align:center;padding:20px">暂无表</div>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card :header="selectedHoloTable ? `${selectedHoloSchema}.${selectedHoloTable} 字段` : '字段预览'" style="height:500px;overflow:auto">
              <div v-if="selectedHoloTable" style="margin-bottom:12px">
                <el-tag type="success" size="small">{{ holoColumns.length }} 列</el-tag>
                <el-tag v-if="holoMeta.metadata_source" size="small" type="info" style="margin-left:4px">
                  来源: {{ METADATA_SOURCE_LABEL[holoMeta.metadata_source] || holoMeta.metadata_source }}
                </el-tag>
                <el-tag v-if="holoMeta.split_pk" size="small" style="margin-left:4px">PK: {{ holoMeta.split_pk }}</el-tag>
              </div>
              <el-alert
                v-if="holoTableHint"
                :title="holoTableHint"
                type="warning"
                :closable="false"
                show-icon
                style="margin-bottom:12px"
              />
              <el-table v-if="holoColumns.length" :data="holoColumns" size="small" border max-height="400">
                <el-table-column prop="column_name" label="字段" min-width="150" />
                <el-table-column prop="data_type" label="类型" width="120" />
                <el-table-column prop="column_key" label="键" width="72" />
              </el-table>
              <el-alert
                v-else-if="holoColumnsError"
                :title="holoColumnsError"
                type="error"
                :closable="false"
                show-icon
                style="margin-top:8px"
              />
              <div v-else-if="selectedHoloTable" style="color:#999;text-align:center;padding:20px">加载中...</div>
              <div v-else style="color:#999;text-align:center;padding:20px">← 请先选择表</div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <!-- MC 表搜索 -->
      <el-tab-pane label="MC 表搜索" name="mc">
        <el-card>
          <el-input v-model="mcKeyword" placeholder="输入关键词搜索 MaxCompute 表（支持中文注释）" clearable
                    style="max-width:500px" @keyup.enter="searchMC">
            <template #append>
              <el-button @click="searchMC" :loading="mcSearching">搜索</el-button>
            </template>
          </el-input>
          <el-alert
            v-if="mcHint"
            :title="mcHint"
            type="info"
            :closable="false"
            show-icon
            style="margin-top:12px"
          />
          <el-table v-if="mcResults.length" :data="mcResults" size="small" border style="margin-top:16px">
            <el-table-column prop="project" label="项目" width="150" />
            <el-table-column prop="table_name" label="表名" min-width="200" />
            <el-table-column prop="comment" label="注释" min-width="200" />
            <el-table-column prop="owner" label="Owner" width="120" />
          </el-table>
          <div v-else-if="mcSearched" style="color:#999;margin-top:16px">无结果</div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { request } from '@/utils/request'

const METADATA_SOURCE_LABEL: Record<string, string> = {
  snapshot: 'schema 快照',
  ddl_registry: 'ODS DDL 登记',
  local_template: '本地 SQL 模板',
  mc_ods_ddl: 'MC 已建 ODS 表',
  inferred: '字段推断',
}

const activeTab = ref('external')

// ── 外部数据源 ──
const dsKeyword = ref('')
const dsTypeFilter = ref('')
const dataSources = ref<any[]>([])
const selectedDS = ref('')
const dsTables = ref<any[]>([])
const tableFilter = ref('')
const selectedTable = ref('')
const dsColumns = ref<any[]>([])

const filteredTables = computed(() =>
  tableFilter.value ? dsTables.value.filter(t => t.name.includes(tableFilter.value)) : dsTables.value
)

let loadDSTimer: ReturnType<typeof setTimeout> | null = null
function debouncedLoadDS() {
  if (loadDSTimer) clearTimeout(loadDSTimer)
  loadDSTimer = setTimeout(loadDataSources, 200)
}

async function loadDataSources() {
  try {
    const params = new URLSearchParams()
    if (dsKeyword.value) params.set('keyword', dsKeyword.value)
    if (dsTypeFilter.value) params.set('type', dsTypeFilter.value)
    const r = await request<{ datasources: any[] }>(`/api/workspace/datasources?${params}`)
    dataSources.value = r.datasources || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载数据源列表失败')
  }
}

async function selectDS(ds: any) {
  selectedDS.value = ds.name
  selectedTable.value = ''
  dsColumns.value = []
  try {
    const r = await request<{ tables: any[] }>(`/api/workspace/datasources/${encodeURIComponent(ds.name)}/tables`)
    dsTables.value = r.tables || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载表列表失败')
    dsTables.value = []
  }
}

async function selectTable(name: string) {
  // 外部数据源在 DataWorks BFF 侧暂无独立的表字段预览接口，
  // 仅能列出表名，故此处只记录所选表、不发起字段请求（D3）。
  selectedTable.value = name
  dsColumns.value = []
}

// ── Holo ──
const holoSchemas = ref<string[]>([])
const selectedHoloSchema = ref('')
const holoTables = ref<any[]>([])
const holoTableFilter = ref('')
const selectedHoloTable = ref('')
const holoColumns = ref<any[]>([])
const holoColumnsError = ref('')
const holoMeta = ref<any>({})
const holoTableHint = ref('')
const holoTableSource = ref('')

const filteredHoloTables = computed(() =>
  holoTableFilter.value ? holoTables.value.filter(t => t.name.includes(holoTableFilter.value)) : holoTables.value
)

async function loadHoloSchemas() {
  try {
    const r = await request<{ schemas: string[] }>('/api/workspace/holo/schemas')
    holoSchemas.value = r.schemas || []
  } catch (e: any) {
    ElMessage.error(e?.message || '加载 Holo Schema 失败')
  }
}

async function loadHoloTables(schema: string) {
  selectedHoloSchema.value = schema
  selectedHoloTable.value = ''
  holoColumns.value = []
  holoColumnsError.value = ''
  holoTableHint.value = ''
  holoTableSource.value = ''
  try {
    const r = await request<{ tables: any[]; source?: string; hint?: string }>(
      `/api/workspace/holo/schemas/${encodeURIComponent(schema)}/tables`
    )
    holoTables.value = r.tables || []
    holoTableSource.value = r.source || ''
    // 当表名来自 MySQL Reader 辅助时后端给出 hint，需透传给用户避免误用（D2）
    holoTableHint.value = r.hint || ''
  } catch (e: any) {
    ElMessage.error(e?.message || '加载 Holo 表列表失败')
    holoTables.value = []
  }
}

async function loadHoloColumns(table: string) {
  selectedHoloTable.value = table
  holoColumns.value = []
  holoColumnsError.value = ''
  holoMeta.value = {}
  try {
    const r = await request<any>(
      `/api/workspace/holo/schemas/${encodeURIComponent(selectedHoloSchema.value)}/tables/${encodeURIComponent(table)}/columns`
    )
    holoColumns.value = r.source_columns || []
    holoMeta.value = { metadata_source: r.metadata_source, split_pk: r.split_pk }
  } catch (e: any) {
    // 字段解析失败（如 ODS 元数据缺失）时给出明确错误，避免 UI 永远卡在"加载中..."（D1）
    holoColumnsError.value = e?.message || '字段预览失败'
    holoColumns.value = []
  }
}

// ── MC 搜索 ──
const mcKeyword = ref('')
const mcResults = ref<any[]>([])
const mcSearching = ref(false)
const mcSearched = ref(false)
const mcHint = ref('')  // 关键字长度不足等场景的轻提示（D6）

async function searchMC() {
  const kw = mcKeyword.value.trim()
  if (kw.length < 2) {
    mcResults.value = []
    mcSearched.value = false
    mcHint.value = '请输入至少 2 个字符'
    mcSearching.value = false
    return
  }
  mcHint.value = ''
  mcSearching.value = true
  mcSearched.value = true
  try {
    const r = await request<{ tables: any[] }>(`/api/workspace/search-tables?keyword=${encodeURIComponent(kw)}`)
    mcResults.value = r.tables || []
  } catch {
    mcResults.value = []
  }
  mcSearching.value = false
}

function _resetMC() {
  mcKeyword.value = ''
  mcResults.value = []
  mcSearched.value = false
  mcSearching.value = false
  mcHint.value = ''
}

onMounted(() => {
  loadDataSources()
  loadHoloSchemas()
})

watch(activeTab, (tab, prev) => {
  // 切出 MC tab 时清空，避免"无结果"横幅跨 tab 残留（D7）
  if (prev === 'mc' && tab !== 'mc') {
    _resetMC()
  }
  if (tab === 'holo' && !holoSchemas.value.length) {
    loadHoloSchemas()
  }
})
</script>

<style scoped>
.ds-item, .table-item {
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 4px;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ds-item:hover, .table-item:hover { background: #f5f7fa; }
.ds-item.active, .table-item.active { background: #ecf5ff; color: #409EFF; }
</style>
