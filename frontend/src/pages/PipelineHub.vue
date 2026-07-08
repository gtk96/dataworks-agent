<template>
  <div>
    <el-tabs v-model="activeTab">
      <el-tab-pane label="OSS 导入" name="oss">
        <el-card header="提交 OSS 批量任务">
          <el-form :model="ossForm" label-width="110px" inline>
            <el-form-item label="OSS 路径"><el-input v-model="ossForm.oss_path" style="width:280px" /></el-form-item>
            <el-form-item label="目标表"><el-input v-model="ossForm.target_table" style="width:220px" /></el-form-item>
            <el-form-item label="格式">
              <el-select v-model="ossForm.file_format" style="width:100px">
                <el-option value="csv" label="csv" />
                <el-option value="parquet" label="parquet" />
              </el-select>
            </el-form-item>
            <el-form-item label="通配符"><el-input v-model="ossForm.wildcard" style="width:120px" /></el-form-item>
            <el-form-item label="调度粒度">
              <el-select v-model="ossForm.schedule_type" style="width:100px">
                <el-option value="day" label="天" />
                <el-option value="hour" label="小时" />
              </el-select>
            </el-form-item>
            <el-form-item label="发布"><el-switch v-model="ossForm.publish" /></el-form-item>
            <el-button type="primary" @click="addOss">加入列表</el-button>
            <el-button @click="previewOss" :loading="previewing">预览 SQL</el-button>
          </el-form>
          <el-table :data="ossList" border size="small" style="margin-top:12px">
            <el-table-column prop="oss_path" label="OSS 路径" />
            <el-table-column prop="target_table" label="目标表" width="200" />
            <el-table-column prop="file_format" label="格式" width="80" />
            <el-table-column label="操作" width="80">
              <template #default="{ $index }">
                <el-button link type="danger" @click="ossList.splice($index, 1)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top:12px">
            <RepositoryPathPicker v-model="nodePathPrefix" label="节点目录（OSS 脚本将创建在此下）" />
          </div>
          <div style="margin-top:12px">
            <el-checkbox v-model="runImmediately">立即执行</el-checkbox>
            <el-button type="success" style="margin-left:12px" @click="submitOssBatch" :loading="submitting">提交 OSS 批次</el-button>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="实时 ODS" name="realtime">
        <el-card header="提交实时同步批次">
          <el-form label-width="110px">
            <el-row :gutter="16">
              <el-col :span="8"><el-form-item label="库名"><el-input v-model="rtForm.database_schema" /></el-form-item></el-col>
              <el-col :span="8"><el-form-item label="表名"><el-input v-model="rtForm.table_name" /></el-form-item></el-col>
              <el-col :span="8">
                <el-form-item label="粒度">
                  <el-select v-model="rtForm.granularity" style="width:100%">
                    <el-option value="hour" label="小时" />
                    <el-option value="day" label="天" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="SELECT DML">
              <el-input v-model="rtForm.select_dml" type="textarea" :rows="3" placeholder="可选，留空则从 sync_rows 推断" />
            </el-form-item>
            <el-form-item label="sync_rows (JSON)">
              <el-input v-model="rtSyncRowsJson" type="textarea" :rows="4" placeholder='[{"field":"value"}]' />
            </el-form-item>
            <el-form-item label="发布"><el-switch v-model="rtForm.publish" /></el-form-item>
            <RepositoryPathPicker v-model="nodePathPrefix" label="节点目录（实时 ODS 脚本将创建在此下）" />
            <div style="margin-top:12px">
              <el-button @click="previewRealtime" :loading="previewing">预览</el-button>
              <el-button type="success" @click="submitRealtimeBatch" :loading="submitting">提交实时批次</el-button>
            </div>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="批次查询" name="batch">
        <el-card header="批次状态">
          <el-input v-model="batchId" placeholder="batch_id" style="width:360px;margin-right:8px" />
          <el-button type="primary" @click="loadBatch" :loading="loadingBatch">查询</el-button>
          <pre v-if="batchDetail" class="code-block" style="margin-top:12px">{{ batchDetail }}</pre>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-alert v-if="message" :type="messageOk ? 'success' : 'error'" :title="message" :closable="false" style="margin-top:16px" />
    <pre v-if="previewText" class="code-block" style="margin-top:12px">{{ previewText }}</pre>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { request } from '@/utils/request'
import RepositoryPathPicker from '@/components/RepositoryPathPicker.vue'

const activeTab = ref('oss')
const ossForm = reactive({
  oss_path: '',
  target_table: '',
  file_format: 'csv',
  wildcard: '',
  schedule_type: 'day',
  publish: true,
})
const ossList = ref<typeof ossForm[]>([])
const rtForm = reactive({
  database_schema: '',
  table_name: '',
  select_dml: '',
  granularity: 'hour',
  publish: true,
})
const rtSyncRowsJson = ref('[]')
const nodePathPrefix = ref('dataworks_agent/01_ODS')
const runImmediately = ref(true)
const submitting = ref(false)
const previewing = ref(false)
const message = ref('')
const messageOk = ref(false)
const previewText = ref('')
const batchId = ref('')
const batchDetail = ref('')
const loadingBatch = ref(false)

function addOss() {
  if (!ossForm.oss_path || !ossForm.target_table) {
    message.value = '请填写 OSS 路径和目标表'
    messageOk.value = false
    return
  }
  ossList.value.push({ ...ossForm })
  ossForm.oss_path = ''
  ossForm.target_table = ''
}

async function previewOss() {
  previewing.value = true
  previewText.value = ''
  try {
    const r = await request<{ sql: string }>('/api/pipeline/preview/oss-sql', { method: 'POST', body: { ...ossForm } })
    previewText.value = r.sql
  } catch (e: any) {
    message.value = e.message
    messageOk.value = false
  }
  previewing.value = false
}

async function submitOssBatch() {
  if (!ossList.value.length) {
    message.value = '请先加入至少一条 OSS 任务'
    messageOk.value = false
    return
  }
  submitting.value = true
  message.value = ''
  try {
    const r = await request<{ batch_id: string; status: string }>('/api/pipeline/oss/batch', {
      method: 'POST',
      body: {
        submissions: ossList.value,
        node_path_prefix: nodePathPrefix.value,
        run_immediately: runImmediately.value,
      },
    })
    message.value = `批次 ${r.batch_id} 已创建 (${r.status})`
    messageOk.value = r.status === 'ok'
    batchId.value = r.batch_id
    activeTab.value = 'batch'
  } catch (e: any) {
    message.value = e.message
    messageOk.value = false
  }
  submitting.value = false
}

async function previewRealtime() {
  previewing.value = true
  previewText.value = ''
  try {
    const sync_rows = JSON.parse(rtSyncRowsJson.value || '[]')
    const r = await request<Record<string, unknown>>('/api/pipeline/preview/realtime', {
      method: 'POST',
      body: { ...rtForm, sync_rows },
    })
    previewText.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    message.value = e.message
    messageOk.value = false
  }
  previewing.value = false
}

async function submitRealtimeBatch() {
  submitting.value = true
  message.value = ''
  try {
    const sync_rows = JSON.parse(rtSyncRowsJson.value || '[]')
    const r = await request<{ batch_id: string; status: string }>('/api/pipeline/realtime/batch', {
      method: 'POST',
      body: {
        submissions: [{ ...rtForm, sync_rows }],
        node_path_prefix: nodePathPrefix.value,
        run_immediately: runImmediately.value,
      },
    })
    message.value = `批次 ${r.batch_id} 已创建 (${r.status})`
    messageOk.value = r.status === 'ok'
    batchId.value = r.batch_id
    activeTab.value = 'batch'
  } catch (e: any) {
    message.value = e.message
    messageOk.value = false
  }
  submitting.value = false
}

async function loadBatch() {
  if (!batchId.value) return
  loadingBatch.value = true
  try {
    const r = await request<Record<string, unknown>>(`/api/pipeline/batches/${encodeURIComponent(batchId.value)}`)
    batchDetail.value = JSON.stringify(r, null, 2)
  } catch (e: any) {
    batchDetail.value = ''
    message.value = e.message
    messageOk.value = false
  }
  loadingBatch.value = false
}
</script>

<style scoped>
.code-block {
  margin: 0;
  padding: 12px;
  background: #f6f8fa;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  max-height: 480px;
  overflow: auto;
  white-space: pre-wrap;
}
</style>
