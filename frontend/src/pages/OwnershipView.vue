<template>
  <div>
    <el-input v-model="searchTable" placeholder="输入表名搜索产权" style="max-width: 400px; margin-bottom: 20px" @change="load" />
    <el-table :data="records">
      <el-table-column prop="table_name" label="表名" />
      <el-table-column prop="field_name" label="字段" />
      <el-table-column prop="created_by_ip" label="创建者 IP" />
      <el-table-column prop="last_modified_by_ip" label="最后修改 IP" />
      <el-table-column prop="business_owner" label="业务负责人" />
      <el-table-column prop="change_type" label="操作" width="80" />
      <el-table-column prop="created_at" label="时间" width="180" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'

const searchTable = ref('')
const records = ref<any[]>([])

async function load() {
  try {
    const r = await request<{ records: any[] }>(`/api/ownership/${searchTable.value || 'all'}`)
    records.value = r.records || []
  } catch {}
}

onMounted(load)
</script>
