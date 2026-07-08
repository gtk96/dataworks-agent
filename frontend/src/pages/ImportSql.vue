<template>
  <div>
    <el-alert type="info" title="批量导入 SQL 建表" description="从本地 .sql 文件批量解析 CREATE TABLE 并执行建表" show-icon style="margin-bottom:20px" />

    <el-form label-position="top" style="max-width:600px">
      <el-form-item label="SQL 目录路径">
        <el-input v-model="path" placeholder="E:/dw-modeling-template/sql/order-fulfillment" />
      </el-form-item>
      <el-row :gutter="12">
        <el-col :span="8">
          <el-form-item label="导入层级">
            <el-select v-model="layer">
              <el-option value="all" label="全部" />
              <el-option value="ods" label="ODS (含DI配置)" />
              <el-option value="dwd" label="DWD" />
              <el-option value="dim" label="DIM" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="调度周期">
            <el-select v-model="schedule">
              <el-option value="auto" label="自动识别" />
              <el-option value="hour" label="小时" />
              <el-option value="day" label="天" />
              <el-option value="none" label="不配置" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="8">
          <el-form-item label="模式">
            <el-radio-group v-model="mode">
              <el-radio value="dry_run">仅预览</el-radio>
              <el-radio value="execute">执行建表</el-radio>
            </el-radio-group>
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item>
        <el-button type="primary" @click="doPreview" :loading="loading">预览</el-button>
        <el-button type="success" @click="doImport" :loading="loading" :disabled="mode==='dry_run'">执行导入</el-button>
      </el-form-item>
    </el-form>

    <!-- 预览结果 -->
    <el-card v-if="preview" header="预览结果" style="margin-top:20px">
      <p>文件数: {{ preview.total_files }}, 表数: {{ preview.total_tables }}</p>
      <div v-for="(v,k) in preview.by_layer" :key="k">
        <el-tag>{{ k }}: {{ v }}</el-tag>
      </div>
      <el-table :data="preview.tables||[]" size="small" max-height="400" style="margin-top:12px">
        <el-table-column prop="table" label="表名" />
        <el-table-column prop="layer" label="层" width="60" />
        <el-table-column prop="update_method" label="更新" width="60" />
        <el-table-column prop="file" label="来源文件" />
      </el-table>
    </el-card>

    <!-- 导入结果 -->
    <el-card v-if="result" header="导入结果" style="margin-top:20px">
      <el-row :gutter="20">
        <el-col :span="8"><el-statistic title="总计" :value="result.total_tables" /></el-col>
        <el-col :span="8"><el-statistic title="成功" :value="result.created">
          <template #suffix><el-tag type="success">✅</el-tag></template>
        </el-statistic></el-col>
        <el-col :span="8"><el-statistic title="失败" :value="result.failed" /></el-col>
      </el-row>
      <el-table :data="result.details||[]" size="small" style="margin-top:12px">
        <el-table-column prop="table" label="表名" />
        <el-table-column prop="status" label="状态" width="80" />
        <el-table-column prop="error" label="错误" />
      </el-table>
    </el-card>

    <!-- 调度配置摘要 -->
    <el-card v-if="scheduleConfigs.length" header="已生成调度配置" style="margin-top:20px">
      <el-table :data="scheduleConfigs" size="small">
        <el-table-column prop="table" label="表名" width="300" />
        <el-table-column prop="cycle" label="周期" width="80" />
        <el-table-column prop="cron" label="Cron" width="180" />
        <el-table-column prop="params" label="参数" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const path = ref('E:/dw-modeling-template/sql/order-fulfillment')
const layer = ref('all')
const schedule = ref('auto')
const mode = ref('dry_run')
const loading = ref(false)
const preview = ref<any>(null)
const result = ref<any>(null)
const scheduleConfigs = ref<any[]>([])

async function doPreview() {
  loading.value = true; result.value = null
  try {
    const params = new URLSearchParams({ path: path.value, layer: layer.value })
    const r = await request<{ tables: { table: string; update_method: string }[] }>(`/api/import/preview?${params}`)
    preview.value = r
    if (schedule.value !== 'none') {
      scheduleConfigs.value = (r.tables || []).map(t => buildSchedule(t.table, t.update_method))
    } else {
      scheduleConfigs.value = []
    }
  } catch (e: any) { ElMessage.error(e.message) }
  loading.value = false
}

function buildSchedule(table: string, updateMethod: string) {
  const isHour = updateMethod === 'hour'
  const cron = isHour ? '00 01 00-23/1 * * ?' : '00 01 03 * * ?'
  const cycle = isHour ? 'NotDaily' : 'Daily'
  const params = isHour
    ? 'bizdate, gmtdate, gmtdate_last1h, hour_last1h, hour_last2h'
    : 'bizdate'
  return { table, cycle, cron, params }
}

async function doImport() {
  loading.value = true; preview.value = null
  try {
    result.value = await request('/api/import/import', {
      method: 'POST',
      body: { path: path.value, layer: layer.value, dry_run: mode.value === 'dry_run' },
    })
    ElMessage.success(`导入完成: ${result.value.created}/${result.value.total_tables}`)
  } catch (e: any) { ElMessage.error(e.message) }
  loading.value = false
}
</script>
