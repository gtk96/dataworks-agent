<template>
  <div>
    <h3>Cookie 配置</h3>
    <el-form label-position="top" style="max-width: 600px">
      <el-form-item label="DataWorks Cookie">
        <el-input v-model="cookieStr" type="textarea" :rows="3" placeholder="粘贴 DataWorks Cookie 字符串" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="saveCookie">保存 Cookie</el-button>
        <el-button @click="autoFetch" :loading="fetching">自动提取</el-button>
        <el-button @click="copyCookie" :loading="copying">复制 Cookie</el-button>
        <el-button type="success" @click="waitLogin" :loading="loggingIn">扫码登录</el-button>
        <el-button @click="launchBrowser">打开 IDE</el-button>
      </el-form-item>
      <el-form-item label="Cookie 状态">
        <el-tag :type="healthTag">{{ healthText }}</el-tag>
        <el-button size="small" @click="verifyCookie" :loading="verifying" style="margin-left:12px">验证</el-button>
        <span v-if="verifyResult" style="margin-left:8px;font-size:12px;color:#666">{{ verifyResult }}</span>
      </el-form-item>
    </el-form>

    <el-divider />

    <h3>服务状态</h3>
    <el-table :data="statusRows" size="small" style="max-width: 600px">
      <el-table-column prop="name" label="组件" width="120" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.ok ? 'success' : 'warning'" size="small">{{ row.ok ? '正常' : '待配置' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="msg" label="详情" />
    </el-table>

    <el-divider />

    <h3>项目参数</h3>
    <el-descriptions border :column="2" style="max-width: 600px">
      <el-descriptions-item label="Project ID">{{ settings.project_id }}</el-descriptions-item>
      <el-descriptions-item label="Region">{{ settings.region }}</el-descriptions-item>
      <el-descriptions-item label="DEV Schema">{{ settings.dev_schema }}</el-descriptions-item>
      <el-descriptions-item label="PROD Schema">{{ settings.prod_schema }}</el-descriptions-item>
      <el-descriptions-item label="端口">{{ settings.port }}</el-descriptions-item>
      <el-descriptions-item label="Cookie 保持">
        <el-tag :type="settings.cookie_keepalive ? 'success' : 'info'" size="small">{{ settings.cookie_keepalive ? '启用' : '禁用' }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="AK/SK 鉴权">
        <el-tag :type="settings.aksk_configured ? 'success' : 'danger'" size="small">{{ settings.aksk_configured ? '已配置' : '未配置' }}</el-tag>
      </el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { request } from '@/utils/request'
import { ElMessage } from 'element-plus'

const cookieStr = ref('')
const fetching = ref(false)
const copying = ref(false)
const loggingIn = ref(false)
const verifying = ref(false)
const verifyResult = ref('')
const healthText = ref('未知')
const healthTag = ref<'success' | 'warning' | 'danger'>('warning')
const settings = ref<any>({})

const smokeResults = computed(() => settings.value.smoke_results || {})

const statusRows = computed(() => {
  const labels: Record<string, string> = {
    mcp: 'MCP 服务', bff: 'BFF API', cdp: 'Chrome CDP', cookie: 'Cookie', db: '数据库',
  }
  return Object.entries(smokeResults.value).map(([key, val]: [string, any]) => ({
    name: labels[key] || key,
    ok: val.ok,
    msg: val.msg || '',
  }))
})

async function refreshStatus() {
  try {
    settings.value = await request('/api/settings')
    const h = await request<{ checks: any }>('/api/health')
    healthText.value = h.checks.cookie_health
    healthTag.value = h.checks.cookie === 'ok' ? 'success' : 'warning'
  } catch {}
}

onMounted(refreshStatus)

async function saveCookie() {
  if (!cookieStr.value) { ElMessage.warning('请输入 Cookie'); return }
  await request('/api/cookie', { method: 'POST', body: { cookie_string: cookieStr.value } })
  ElMessage.success('Cookie 已保存')
  setTimeout(refreshStatus, 500)
}

async function autoFetch() {
  fetching.value = true
  try {
    const r = await request<{ message: string }>('/api/cookie/auto-fetch', { method: 'POST' })
    ElMessage.success(r.message || 'Cookie 已自动提取')
    setTimeout(refreshStatus, 1000)
  } catch (e: any) { ElMessage.error(e.message) }
  fetching.value = false
}

async function verifyCookie() {
  verifying.value = true
  verifyResult.value = ''
  try {
    const r = await request<{ overall: string; channels: Record<string, { status: string; error?: string }> }>('/api/cookie/verify')
    verifyResult.value = Object.entries(r.channels).map(([k, v]) => `${k}: ${v.status}`).join(' | ')
    ElMessage.success('验证完成')
  } catch (e: any) { ElMessage.error(e.message) }
  verifying.value = false
}

async function waitLogin() {
  loggingIn.value = true
  try {
    const r = await request<{ status: string; message: string }>('/api/cookie/wait-login', { method: 'POST' })
    ElMessage.success(r.message || '登录成功')
    await refreshStatus()
  } catch (e: any) {
    if (e.message?.includes('408')) {
      ElMessage.warning('登录超时，请在浏览器中手动扫码后点"自动提取"')
    } else {
      ElMessage.error(e.message)
    }
  }
  loggingIn.value = false
}

async function launchBrowser() {
  try {
    await request('/api/cookie/launch-browser', { method: 'POST' })
    ElMessage.success('浏览器已导航到 DataWorks IDE')
  } catch (e: any) { ElMessage.error(e.message) }
}

async function copyCookie() {
  copying.value = true
  try {
    const r = await request<{ cookie: string }>('/api/cookie/full')
    if (r.cookie) {
      await navigator.clipboard.writeText(r.cookie)
      ElMessage.success(`已复制 Cookie (${r.cookie.length} 字符)`)
    } else {
      ElMessage.warning('Cookie 为空')
    }
  } catch (e: any) {
    // 降级: 用 textarea
    try {
      const r = await request<{ cookie: string }>('/api/cookie/full')
      const ta = document.createElement('textarea')
      ta.value = r.cookie
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      ElMessage.success(`已复制 Cookie (${r.cookie.length} 字符)`)
    } catch (e2: any) {
      ElMessage.error('复制失败: ' + (e2.message || e.message))
    }
  }
  copying.value = false
}
</script>
