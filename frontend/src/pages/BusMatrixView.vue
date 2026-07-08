<template>
  <div>
    <el-card header="总线矩阵">
      <el-table :data="rows" border>
        <el-table-column prop="dimension" label="维度" width="150" fixed />
        <el-table-column v-for="d in domains" :key="d" :label="d" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.domains?.[d]" type="success">✓</el-tag>
            <span v-else style="color:#ccc">—</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { request } from '@/utils/request'

const domains = ref<string[]>([])
const rows = ref<any[]>([])

onMounted(async () => {
  try {
    const r = await request<{ matrix: any[] }>('/api/bus-matrix')
    // Transform into table format
    const dimMap: Record<string, Record<string, boolean>> = {}
    const domainSet = new Set<string>()
    for (const entry of r.matrix || []) {
      domainSet.add(entry.domain)
      if (!dimMap[entry.dimension]) dimMap[entry.dimension] = {}
      dimMap[entry.dimension][entry.domain] = entry.has_link
    }
    domains.value = [...domainSet]
    rows.value = Object.entries(dimMap).map(([dim, dmap]) => ({ dimension: dim, domains: dmap }))
  } catch {}
})
</script>
