<template>
  <div>
    <!-- 层选择器 -->
    <el-card style="margin-bottom:16px">
      <el-row :gutter="16" align="middle">
        <el-col :span="8">
          <el-form-item label="目标层" style="margin-bottom:0">
            <el-radio-group v-model="layer" @change="onLayerChange">
              <el-radio-button value="DWD">DWD</el-radio-button>
              <el-radio-button value="DWS">DWS</el-radio-button>
              <el-radio-button value="DMR">DMR</el-radio-button>
              <el-radio-button value="DIM">DIM</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
        <el-col :span="16" style="text-align:right">
          <el-tag type="info" size="small">{{ layerDesc }}</el-tag>
        </el-col>
      </el-row>
    </el-card>

    <!-- ========== 向导模式（DWD/DWS/DMR/DIM） ========== -->
    <div style="max-width:900px;margin:0 auto">
        <el-steps :active="step" finish-status="success" align-center style="margin-bottom:30px">
          <el-step title="源表选择" />
          <el-step title="目标配置" />
          <el-step title="调度配置" />
          <el-step title="预览确认" />
          <el-step title="提交执行" />
        </el-steps>

        <!-- Step 1: 源表选择 -->
        <el-card v-if="step === 0">
          <template #header>步骤 1: 选择源表</template>
          <el-form label-position="top">
            <el-form-item label="主表（MaxCompute）">
              <el-select v-model="form.source_table" filterable remote :remote-method="searchSource"
                :loading="searching" placeholder="输入关键词搜索..." style="width:100%" clearable>
                <el-option v-for="t in sourceTables" :key="t.table_name"
                  :label="`${t.project}.${t.table_name}`" :value="`${t.project}.${t.table_name}`">
                  <span>{{ t.project }}.{{ t.table_name }}</span>
                  <span style="float:right;color:#999;font-size:12px">{{ t.comment }}</span>
                </el-option>
              </el-select>
            </el-form-item>

            <!-- DWD: 关联表 -->
            <template v-if="layer === 'DWD'">
              <el-divider content-position="left">关联表（JOIN）</el-divider>
              <div v-for="(src, i) in dwd.extra_sources" :key="i" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
                <el-select v-model="src.table_name" filterable remote :remote-method="searchSource"
                  :loading="searching" placeholder="关联表" style="flex:1" clearable>
                  <el-option v-for="t in sourceTables" :key="t.table_name"
                    :label="`${t.project}.${t.table_name}`" :value="`${t.project}.${t.table_name}`" />
                </el-select>
                <el-input v-model="src.alias" placeholder="别名" style="width:120px" />
                <el-select v-model="src.join_type" style="width:100px">
                  <el-option value="LEFT" label="LEFT JOIN" />
                  <el-option value="INNER" label="INNER JOIN" />
                </el-select>
                <el-input v-model="src.on_condition" placeholder="a.id = b.id" style="flex:1" />
                <el-button type="danger" link @click="dwd.extra_sources.splice(i, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="dwd.extra_sources.push({ table_name:'', alias:'', join_type:'LEFT', on_condition:'' })">
                + 添加关联表
              </el-button>
            </template>
          </el-form>
          <el-button type="primary" @click="step = 1" :disabled="!form.source_table">下一步</el-button>
        </el-card>

        <!-- Step 2: 目标配置 -->
        <el-card v-if="step === 1">
          <template #header>步骤 2: 配置目标表</template>
          <el-form label-position="top">
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="主题域"><el-input v-model="form.domain" placeholder="mkt" /></el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="实体名"><el-input v-model="form.entity" placeholder="ad_group" /></el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="更新方式">
                  <el-select v-model="form.update_method">
                    <el-option value="day" label="天" />
                    <el-option value="hour" label="小时" />
                    <el-option value="hourly" label="每小时" />
                    <el-option value="all" label="全量" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>

            <!-- DWD: 字段映射 -->
            <template v-if="layer === 'DWD'">
              <el-divider content-position="left">字段映射</el-divider>
              <div v-for="(fm, i) in dwd.field_mappings" :key="i" style="display:flex;gap:8px;margin-bottom:8px;align-items:center">
                <el-input v-model="fm.source_field" placeholder="源字段" style="flex:1" />
                <span>→</span>
                <el-input v-model="fm.target_field" placeholder="目标字段" style="flex:1" />
                <el-input v-model="fm.transform" placeholder="转换(可选)" style="flex:1" />
                <el-button type="danger" link @click="dwd.field_mappings.splice(i, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="dwd.field_mappings.push({ source_field:'', target_field:'', transform:'' })">
                + 添加字段映射
              </el-button>
              <el-form-item label="主键（去重用）" style="margin-top:12px">
                <el-select v-model="dwd.primary_keys" multiple filterable allow-create placeholder="选择或输入主键字段" style="width:100%">
                  <el-option v-for="fm in dwd.field_mappings" :key="fm.target_field" :value="fm.target_field" :label="fm.target_field" />
                </el-select>
              </el-form-item>
            </template>
          </el-form>
          <el-button @click="step = 0">上一步</el-button>
          <el-button type="primary" @click="step = 2" :disabled="!form.entity">下一步</el-button>
        </el-card>

        <!-- Step 3: 调度配置 -->
        <el-card v-if="step === 2">
          <template #header>步骤 3: 调度配置</template>
          <el-form label-position="top">
            <el-form-item label="调度周期">
              <el-radio-group v-model="schedule.cycle_type">
                <el-radio value="Daily">天级</el-radio>
                <el-radio value="NotDaily">小时/分钟级</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="schedule.cycle_type === 'Daily'" label="调度时间（小时）">
              <el-input-number v-model="schedule.biz_hour" :min="0" :max="23" />
            </el-form-item>
            <el-form-item v-else label="Cron 表达式">
              <el-input v-model="schedule.cron" placeholder="00 00 00-23/1 * * ?" />
            </el-form-item>
            <el-button @click="step = 1">上一步</el-button>
            <el-button type="primary" @click="doPreview">预览 DDL</el-button>
          </el-form>
        </el-card>

        <!-- Step 4: 预览确认 -->
        <el-card v-if="step === 3">
          <template #header>步骤 4: 预览确认</template>
          <div v-if="previewLoading"><el-icon class="is-loading"><Loading /></el-icon> 生成中...</div>
          <div v-else-if="preview">
            <h4>DEV DDL</h4>
            <pre style="background:#f5f5f5;padding:12px;overflow-x:auto;font-size:12px">{{ preview.ddl_dev }}</pre>
            <h4>PROD DDL</h4>
            <pre style="background:#f5f5f5;padding:12px;overflow-x:auto;font-size:12px">{{ preview.ddl_prod }}</pre>
            <template v-if="preview.dml">
              <h4>DML</h4>
              <pre style="background:#f5f5f5;padding:12px;overflow-x:auto;font-size:12px">{{ preview.dml }}</pre>
            </template>

            <!-- DDL 规范检查 -->
            <div v-if="ddlCheck" style="margin-top:16px">
              <el-alert
                :type="ddlCheck.passed ? 'success' : 'warning'"
                :closable="false"
                show-icon
              >
                <template #title>
                  DDL 规范检查：{{ ddlCheck.passed ? '通过' : '有问题' }}
                </template>
                <template #default>
                  <div v-if="ddlCheck.errors.length" style="margin-top:8px">
                    <div v-for="e in ddlCheck.errors" :key="e" style="color:#F56C6C">❌ {{ e }}</div>
                  </div>
                  <div v-if="ddlCheck.warnings.length" style="margin-top:8px">
                    <div v-for="w in ddlCheck.warnings" :key="w" style="color:#E6A23C">⚠️ {{ w }}</div>
                  </div>
                </template>
              </el-alert>
            </div>
          </div>
          <el-button @click="step = 2">上一步</el-button>
          <el-button type="success" @click="step = 4">确认提交</el-button>
        </el-card>

        <!-- Step 5: 提交执行 -->
        <el-card v-if="step === 4">
          <template #header>步骤 5: 提交执行</template>
          <div v-if="submitting"><el-progress :percentage="100" :indeterminate="true" /> 提交中...</div>
          <div v-else-if="taskId">
            <el-result icon="success" title="任务已创建" :sub-title="`任务 ID: ${taskId}`">
              <template #extra>
                <el-button type="primary" @click="$router.push(`/tasks/${taskId}`)">查看任务详情</el-button>
                <el-button @click="$router.push('/tasks')">返回列表</el-button>
              </template>
            </el-result>
          </div>
          <div v-else>
            <el-descriptions border :column="2">
              <el-descriptions-item label="源表">{{ form.source_table }}</el-descriptions-item>
              <el-descriptions-item label="目标层">{{ layer }}</el-descriptions-item>
              <el-descriptions-item label="域">{{ form.domain }}</el-descriptions-item>
              <el-descriptions-item label="实体">{{ form.entity }}</el-descriptions-item>
              <el-descriptions-item label="更新方式">{{ form.update_method }}</el-descriptions-item>
              <el-descriptions-item label="调度">{{ schedule.cycle_type }}</el-descriptions-item>
            </el-descriptions>
            <el-button @click="step = 3">上一步</el-button>
            <el-button type="danger" @click="doSubmit">确认提交</el-button>
          </div>
        </el-card>
      </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { request, idempotencyKey } from '@/utils/request'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

// ── 层选择 ──
const layer = ref('DWD')

const layerDesc = computed(() => {
  const map: Record<string, string> = {
    DWD: '明细层 — ODS→DWD，支持 JOIN 和字段映射',
    DWS: '汇总层 — DWD/DIM→DWS，聚合指标',
    DMR: '集市层 — DWS→DMR，业务集市',
    DIM: '维度层 — ODS→DIM，维度表',
  }
  return map[layer.value] || ''
})

function onLayerChange() {
  step.value = 0
  form.value.target_layer = layer.value
  dwd.value = { extra_sources: [], field_mappings: [], primary_keys: [] }
}

// ── 向导模式 ──
const step = ref(0)
const form = ref({
  source_table: '', source_datasource_name: '',
  target_layer: 'DWD', domain: 'mkt', entity: '', update_method: 'day',
  partition_keys: [] as string[],
})
const sourceTables = ref<any[]>([])
const searching = ref(false)

const dwd = ref({
  extra_sources: [] as { table_name: string; alias: string; join_type: string; on_condition: string }[],
  field_mappings: [] as { source_field: string; target_field: string; transform: string }[],
  primary_keys: [] as string[],
})

async function searchSource(keyword: string) {
  if (keyword.length < 2) return
  searching.value = true
  try {
    const r = await request<{ tables: any[] }>(`/api/workspace/search-tables?keyword=${encodeURIComponent(keyword)}`)
    sourceTables.value = r.tables || []
  } catch {}
  searching.value = false
}

const schedule = ref({ cycle_type: 'Daily', biz_hour: 7, cron: '00 00 00-23/1 * * ?' })
const preview = ref<any>(null)
const previewLoading = ref(false)
const ddlCheck = ref<{ passed: boolean; errors: string[]; warnings: string[] } | null>(null)
const taskId = ref('')
const submitting = ref(false)

function buildBody() {
  const body: any = {
    source_table: form.value.source_table,
    target_layer: layer.value,
    domain: form.value.domain,
    entity: form.value.entity,
    update_method: form.value.update_method,
    schedule_config: schedule.value,
  }
  if (layer.value === 'DWD') {
    const mainAlias = form.value.entity || 't'
    body.dwd_metadata = {
      sources: [
        { table_name: form.value.source_table, alias: mainAlias },
        ...dwd.value.extra_sources.filter(s => s.table_name),
      ],
      joins: dwd.value.extra_sources.filter(s => s.table_name).map(s => ({
        join_type: s.join_type, right_table_name: s.table_name,
        right_alias: s.alias, on_condition: s.on_condition,
      })),
      field_mappings: dwd.value.field_mappings.filter(f => f.target_field).map(f => ({
        source_alias: mainAlias, source_field_name: f.source_field,
        target_field_name: f.target_field, transform_sql: f.transform || null,
      })),
      logical_primary_keys: dwd.value.primary_keys,
    }
  }
  return body
}

async function doPreview() {
  previewLoading.value = true
  ddlCheck.value = null
  step.value = 3
  try {
    preview.value = await request('/api/modeling/preview', {
      method: 'POST', body: { ...buildBody(), dry_run: true },
    })
    if (preview.value?.ddl_dev) {
      try {
        ddlCheck.value = await request('/api/governance/check-ddl', {
          method: 'POST', body: { ddl: preview.value.ddl_dev },
        })
      } catch {}
    }
  } catch (e: any) {
    ElMessage.error(`预览失败: ${e.message}`)
  }
  previewLoading.value = false
}

async function doSubmit() {
  submitting.value = true
  try {
    const key = idempotencyKey()
    const result = await request<{ task_id: string }>('/api/modeling/tasks', {
      method: 'POST',
      headers: { 'X-Idempotency-Key': key },
      body: { ...buildBody(), dry_run: false },
    })
    taskId.value = result.task_id
  } catch (e: any) {
    ElMessage.error(`提交失败: ${e.message}`)
  }
  submitting.value = false
}
</script>