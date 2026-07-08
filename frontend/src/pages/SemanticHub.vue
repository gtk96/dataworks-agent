<template>
  <div v-loading="loading">
    <el-card>
      <template #header>语义层管理</template>
      
      <el-tabs v-model="activeTab">
        <!-- 语义定义 -->
        <el-tab-pane label="语义定义" name="definitions">
          <div style="display: flex; gap: 8px; margin-bottom: 16px; align-items: center">
            <el-input v-model="searchQuery" placeholder="搜索标识、类型..." clearable style="width: 240px" @clear="loadDefinitions" @keyup.enter="loadDefinitions" />
            <el-select v-model="filterKind" placeholder="类型筛选" clearable style="width: 120px" @change="loadDefinitions">
              <el-option label="metric" value="metric" />
              <el-option label="caliber" value="caliber" />
              <el-option label="dimension" value="dimension" />
              <el-option label="alias" value="alias" />
              <el-option label="rule" value="rule" />
            </el-select>
            <el-select v-model="filterStatus" placeholder="状态筛选" clearable style="width: 140px" @change="loadDefinitions">
              <el-option label="草稿 (draft)" value="draft" />
              <el-option label="已批准 (approved)" value="approved" />
              <el-option label="已删除 (deleted)" value="deleted" />
            </el-select>
            <el-button type="primary" @click="loadDefinitions" :loading="loading">搜索</el-button>
            <el-button type="success" @click="showCreateDialog">新建</el-button>
          </div>
          <el-alert v-if="filterStatus === 'deleted'" title="已删除的定义可点击「恢复」按钮还原" type="info" show-icon style="margin-bottom: 12px" />
          <el-table :data="definitions" style="width: 100%">
            <el-table-column prop="def_id" label="ID" width="120" />
            <el-table-column prop="kind" label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ row.kind }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="key" label="标识" width="150" />
            <el-table-column prop="version" label="版本" width="80" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'approved' ? 'success' : 'info'" size="small">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="250">
              <template #default="{ row }">
                <el-button v-if="row.status === 'draft'" size="small" type="success" @click="approveDefinition(row.def_id)">
                  批准
                </el-button>
                <el-button v-if="row.status === 'deleted'" size="small" type="warning" @click="restoreDefinition(row.def_id)">
                  恢复
                </el-button>
                <el-button v-if="row.status !== 'deleted'" size="small" type="primary" @click="showEditDialog(row)">
                  编辑
                </el-button>
                <el-button v-if="row.status !== 'deleted'" size="small" type="danger" @click="deleteDefinition(row.def_id)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
          <div style="margin-top: 16px; display: flex; justify-content: flex-end">
            <el-pagination
              v-model:current-page="currentPage"
              v-model:page-size="pageSize"
              :page-sizes="[10, 20, 50, 100]"
              :total="totalDefinitions"
              layout="total, sizes, prev, pager, next"
              @size-change="loadDefinitions"
              @current-change="loadDefinitions"
            />
          </div>
        </el-tab-pane>

        <!-- 口径澄清 -->
        <el-tab-pane label="口径澄清" name="caliber">
          <el-form inline>
            <el-form-item label="指标 ID">
              <el-input v-model="caliberForm.metric_id" placeholder="order_count" />
            </el-form-item>
            <el-form-item label="预期口径">
              <el-input v-model="caliberForm.expected_caliber" placeholder="订单数量" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="clarifyCaliber" :loading="caliberLoading">澄清</el-button>
            </el-form-item>
          </el-form>
          
          <el-card v-if="caliberResult" style="margin-top: 16px">
            <el-descriptions :column="2">
              <el-descriptions-item label="指标">{{ caliberResult.metric_id }}</el-descriptions-item>
              <el-descriptions-item label="口径匹配">
                <el-tag :type="caliberResult.caliber_match ? 'success' : 'danger'">
                  {{ caliberResult.caliber_match ? '匹配' : '不匹配' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="根因">{{ caliberResult.root_cause }}</el-descriptions-item>
              <el-descriptions-item label="解释">{{ caliberResult.explanation }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-tab-pane>

        <!-- 质量信号 -->
        <el-tab-pane label="质量信号" name="quality">
          <el-form inline>
            <el-form-item label="表名">
              <el-input v-model="qualityForm.table_name" placeholder="dwd_ord_order_day" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="getQualitySignal" :loading="qualityLoading">查询</el-button>
            </el-form-item>
          </el-form>
          
          <el-card v-if="qualityResult" style="margin-top: 16px">
            <el-descriptions :column="2">
              <el-descriptions-item label="表名">{{ qualityResult.table_name }}</el-descriptions-item>
              <el-descriptions-item label="新鲜度">{{ qualityResult.freshness }}</el-descriptions-item>
              <el-descriptions-item label="完整性">{{ qualityResult.completeness }}</el-descriptions-item>
              <el-descriptions-item label="唯一性">{{ qualityResult.uniqueness }}</el-descriptions-item>
              <el-descriptions-item label="质量状态">{{ qualityResult.quality_status }}</el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 新建/编辑对话框 -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="600px">
      <el-form label-width="80px">
        <el-form-item label="类型">
          <el-select v-model="dialogForm.kind" placeholder="选择类型">
            <el-option label="metric" value="metric" />
            <el-option label="caliber" value="caliber" />
            <el-option label="dimension" value="dimension" />
            <el-option label="alias" value="alias" />
            <el-option label="rule" value="rule" />
          </el-select>
        </el-form-item>
        <el-form-item label="标识">
          <el-input v-model="dialogForm.key" placeholder="order_count" />
        </el-form-item>
        <el-form-item label="定义内容">
          <el-input v-model="dialogForm.bodyJson" type="textarea" :rows="6" placeholder='{"caliber": "订单数量", "type": "count"}' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveDefinition" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const activeTab = ref('definitions')
const definitions = ref<any[]>([])
const totalDefinitions = ref(0)
const currentPage = ref(1)
const pageSize = ref(10)
const searchQuery = ref('')
const filterKind = ref('')
const filterStatus = ref('')

// 口径澄清
const caliberForm = ref({ metric_id: '', expected_caliber: '' })
const caliberLoading = ref(false)
const caliberResult = ref<any>(null)

// 质量信号
const qualityForm = ref({ table_name: '' })
const qualityLoading = ref(false)
const qualityResult = ref<any>(null)

// 对话框
const dialogVisible = ref(false)
const dialogTitle = ref('新建定义')
const dialogForm = ref({ def_id: '', kind: 'metric', key: '', bodyJson: '{}' })
const saving = ref(false)
const isEdit = ref(false)

onMounted(() => {
  loadDefinitions()
})

async function loadDefinitions() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    if (searchQuery.value) params.append('search', searchQuery.value)
    if (filterKind.value) params.append('kind', filterKind.value)
    if (filterStatus.value) params.append('status', filterStatus.value)
    params.append('page', currentPage.value.toString())
    params.append('page_size', pageSize.value.toString())
    
    const r = await request<{ definitions: any[]; total: number }>(`/api/semantic/definitions?${params.toString()}`)
    definitions.value = r.definitions || []
    totalDefinitions.value = r.total || 0
  } catch (e: any) {
    ElMessage.error(`加载失败: ${e.message}`)
  }
  loading.value = false
}

function showCreateDialog() {
  isEdit.value = false
  dialogTitle.value = '新建定义'
  dialogForm.value = { def_id: '', kind: 'metric', key: '', bodyJson: '{}' }
  dialogVisible.value = true
}

function showEditDialog(row: any) {
  isEdit.value = true
  dialogTitle.value = '编辑定义'
  dialogForm.value = {
    def_id: row.def_id,
    kind: row.kind,
    key: row.key,
    bodyJson: JSON.stringify(row.body, null, 2),
  }
  dialogVisible.value = true
}

async function saveDefinition() {
  saving.value = true
  try {
    const body = {
      kind: dialogForm.value.kind,
      key: dialogForm.value.key,
      body: JSON.parse(dialogForm.value.bodyJson),
      actor: 'web',
    }

    if (isEdit.value) {
      await request(`/api/semantic/definitions/${dialogForm.value.def_id}`, {
        method: 'PUT',
        body,
      })
      ElMessage.success('更新成功')
    } else {
      await request('/api/semantic/definitions', {
        method: 'POST',
        body,
      })
      ElMessage.success('创建成功')
    }

    dialogVisible.value = false
    loadDefinitions()
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.message}`)
  }
  saving.value = false
}

async function approveDefinition(defId: string) {
  try {
    await request(`/api/semantic/definitions/${defId}/approve`, { method: 'POST' })
    ElMessage.success('批准成功')
    loadDefinitions()
  } catch (e: any) {
    ElMessage.error(`批准失败: ${e.message}`)
  }
}

async function deleteDefinition(defId: string) {
  try {
    await ElMessageBox.confirm('确定删除该定义？', '确认', { type: 'warning' })
    await request(`/api/semantic/definitions/${defId}`, { method: 'DELETE' })
    ElMessage.success('删除成功（可恢复）')
    loadDefinitions()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(`删除失败: ${e.message}`)
    }
  }
}

async function restoreDefinition(defId: string) {
  try {
    await request(`/api/semantic/definitions/${defId}/restore`, { method: 'POST' })
    ElMessage.success('恢复成功')
    loadDefinitions()
  } catch (e: any) {
    ElMessage.error(`恢复失败: ${e.message}`)
  }
}

async function clarifyCaliber() {
  caliberLoading.value = true
  try {
    caliberResult.value = await request('/api/semantic/caliber/clarify', {
      method: 'POST',
      body: caliberForm.value,
    })
  } catch (e: any) {
    ElMessage.error(`澄清失败: ${e.message}`)
  }
  caliberLoading.value = false
}

async function getQualitySignal() {
  qualityLoading.value = true
  try {
    qualityResult.value = await request(`/api/semantic/quality/${qualityForm.value.table_name}`)
  } catch (e: any) {
    ElMessage.error(`查询失败: ${e.message}`)
  }
  qualityLoading.value = false
}
</script>
