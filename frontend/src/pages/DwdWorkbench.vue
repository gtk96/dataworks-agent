<template>
  <div>
    <el-row :gutter="16">
      <el-col :span="14">
        <el-card header="structured_metadata (JSON)">
          <el-input
            v-model="metadataJson"
            type="textarea"
            :rows="22"
            placeholder="输入 DWD 可视化建模 JSON"
            style="font-family: monospace; font-size: 13px"
          />
          <div style="margin-top:12px">
            <el-button @click="loadSample">加载示例</el-button>
            <el-button type="primary" @click="previewDdl" :loading="loading.ddl">预览 DDL</el-button>
            <el-button type="primary" @click="previewSql" :loading="loading.sql">预览 SQL</el-button>
            <el-button @click="resolveTypes" :loading="loading.types">解析类型</el-button>
          </div>
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card header="部署选项">
          <el-form label-width="100px">
            <el-form-item label="节点路径">
              <el-input v-model="deploy.node_path" />
            </el-form-item>
            <el-form-item label="节点名称">
              <el-input v-model="deploy.node_name" placeholder="可选" />
            </el-form-item>
            <el-form-item label="MC 项目">
              <el-input v-model="deploy.mc_project" placeholder="留空用默认" />
            </el-form-item>
            <el-form-item label="调度分钟">
              <el-input-number v-model="deploy.schedule_minute" :min="0" :max="59" />
            </el-form-item>
            <el-form-item label="自动发布">
              <el-switch v-model="deploy.publish" />
            </el-form-item>
            <el-button type="success" @click="deployDwd" :loading="loading.deploy">六步部署</el-button>
          </el-form>
        </el-card>
        <el-card header="输出" style="margin-top:16px">
          <el-alert v-if="output.error" type="error" :title="output.error" :closable="false" style="margin-bottom:8px" />
          <el-descriptions v-if="output.meta" border :column="1" size="small" style="margin-bottom:8px">
            <el-descriptions-item v-for="(v, k) in output.meta" :key="k" :label="String(k)">{{ v }}</el-descriptions-item>
          </el-descriptions>
          <CodeBlock v-if="output.text">{{ output.text }}</CodeBlock>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { request } from '@/utils/request'
import CodeBlock from '@/components/CodeBlock.vue'

const SAMPLE = {
  targets: [
    {
      table_name: 'dwd_ord_order_hour',
      table_comment: '订单小时表',
      update_mode: 'hourly',
      partition_fields: ['dt', 'ht'],
      logical_primary_keys: ['order_id'],
      fields: [
        { name: 'order_id', type: 'STRING', comment: '订单ID' },
        { name: 'pay_amt', type: 'DECIMAL(24,6)', comment: '支付金额' },
        { name: 'dt', type: 'STRING' },
        { name: 'ht', type: 'STRING' },
      ],
    },
  ],
  sources: [{ table_name: 'ods_hl_oms__order_hour', alias: 'T1', is_master: true }],
  field_mappings: [
    { source_alias: 'T1', source_field_name: 'order_id', target_field_name: 'order_id', field_category: 'normal' },
    { source_alias: 'T1', source_field_name: 'pay_amt', target_field_name: 'pay_amt', field_category: 'amount' },
  ],
  joins: [],
}

const metadataJson = ref(JSON.stringify(SAMPLE, null, 2))
const loading = reactive({ ddl: false, sql: false, types: false, deploy: false })
const deploy = reactive({
  node_path: 'dataworks_agent/02_DWD',
  node_name: '',
  mc_project: '',
  schedule_minute: 1,
  publish: true,
})
const output = reactive<{ error: string; text: string; meta: Record<string, unknown> | null }>({
  error: '',
  text: '',
  meta: null,
})

function parsePayload(): Record<string, unknown> {
  try {
    return JSON.parse(metadataJson.value)
  } catch {
    throw new Error('JSON 格式无效')
  }
}

function loadSample() {
  metadataJson.value = JSON.stringify(SAMPLE, null, 2)
}

async function previewDdl() {
  loading.ddl = true
  output.error = ''
  output.text = ''
  output.meta = null
  try {
    const r = await request<{ ddl: string; target_table: string }>('/api/dwd/preview-ddl', {
      method: 'POST',
      body: { structured_metadata: parsePayload() },
    })
    output.meta = { target_table: r.target_table }
    output.text = r.ddl
  } catch (e: any) {
    output.error = e.message
  }
  loading.ddl = false
}

async function previewSql() {
  loading.sql = true
  output.error = ''
  output.text = ''
  output.meta = null
  try {
    const r = await request<{ sql: string; target_table: string; update_mode: string }>('/api/dwd/preview-sql', {
      method: 'POST',
      body: { structured_metadata: parsePayload() },
    })
    output.meta = { target_table: r.target_table, update_mode: r.update_mode }
    output.text = r.sql
  } catch (e: any) {
    output.error = e.message
  }
  loading.sql = false
}

async function resolveTypes() {
  loading.types = true
  output.error = ''
  output.text = ''
  output.meta = null
  try {
    const r = await request<{ fields: unknown[] }>('/api/dwd/resolve-types', {
      method: 'POST',
      body: { structured_metadata: parsePayload() },
    })
    output.text = JSON.stringify(r.fields || r, null, 2)
  } catch (e: any) {
    output.error = e.message
  }
  loading.types = false
}

async function deployDwd() {
  loading.deploy = true
  output.error = ''
  output.text = ''
  output.meta = null
  try {
    const r = await request<Record<string, unknown>>('/api/dwd/deploy', {
      method: 'POST',
      body: {
        structured_metadata: parsePayload(),
        node_path: deploy.node_path,
        node_name: deploy.node_name || null,
        mc_project: deploy.mc_project,
        schedule_minute: deploy.schedule_minute,
        publish: deploy.publish,
      },
    })
    output.meta = { status: r.status, success: r.success }
    output.text = JSON.stringify(r, null, 2)
  } catch (e: any) {
    output.error = e.message
  }
  loading.deploy = false
}
</script>
