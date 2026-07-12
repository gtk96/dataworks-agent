// fake BFF server — Playwright E2E 测试用,无依赖,接 /api/* 返回 mock JSON
// 跑在 :8086, 配合 vite proxy /api → http://localhost:8086
//
// === Mock 清单 ===
// 任何 E2E 用到的端点必须在此显式注册；未注册的 endpoint 一律返回 404，
// 把"测试覆盖盲区"暴露出来而不是用 `{ok:true}` 蒙混。
//
// 已 mock 的 URL（动态数量多以 MOCKS 与下方的 if-else 形式列出，详见行内）：
//   GET  /api/health                            → 健康探针
//   GET  /api/settings                           → 项目设置
//   GET  /api/metrics                            → Prometheus 文本
//   GET  /api/governance/{check-ddl,parse-sql-lineage,parse-table-name,
//                          infer-update-mode,word-roots,...}   → 见 MOCKS 表
//   GET  /api/governance/conventions/*          → 动态返回 {error:'not found'}
//   POST /api/modeling/tasks                     → 创建任务（固定格式 ID）
//   POST /api/{sync/diff,sync/execute}           → 同步差异/执行（无变化）
//   POST /api/import/import                      → SQL 导入（空结果）
//   POST /api/governance/{check-ddl,parse-sql-lineage,parse-table-name,
//                          infer-update-mode}     → 详见行内 if-else
//
// 未注册的 endpoint：返回 404 {error:'not mocked', url}。

import http from 'node:http'

const PORT = 8086

const OK = (res, body) => {
  res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(body))
}

const NOT_MOCKED = (res, url) => {
  res.writeHead(404, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify({ error: 'not mocked', url }))
}

const MOCKS = {
  '/api/health': { status: 'ok', checks: { cookie: 'fake', mcp: 'fake', bff: 'fake' } },
  '/api/settings': { project_id: 0, region: 'cn-shenzhen', dev_schema: 'dataworks_dev', prod_schema: 'dataworks' },
  '/api/metrics': 'fake_metrics_200_ok\n',

  '/api/governance/word-roots': {
    status: 'ok',
    total: 4,
    entries: [
      { column_name: 'order_id', column_desc: '订单ID', is_digit: false },
      { column_name: 'order_amt', column_desc: '订单金额', is_digit: false },
      { column_name: 'order_cnt', column_desc: '订单数量', is_digit: true },
      { column_name: 'order_status', column_desc: '订单状态', is_digit: false },
    ],
  },
  '/api/governance/parse-sql-lineage': {
    status: 'ok',
    source_tables: ['ods_src', 'ods_dim'],
    joins: [{ left: 'ods_src.id', right: 'ods_dim.id' }],
  },
  '/api/governance/check-ddl': { passed: true, errors: [], warnings: [] },
  '/api/governance/lineage/preview': { nodes: [{ id: 'n1', table: 'dwd_test' }], edges: [] },
  '/api/governance/lineage/export': { file_path: '/tmp/lineage.zip', total_nodes: 1 },
  '/api/governance/parse-table-name': {
    status: 'ok',
    parsed: {
      layer: 'DWD',
      domain: 'ord',
      entity: 'ofc_s_order',
      update_mode: 'hour',
      description: 'OFC s_order',
    },
  },
  '/api/governance/infer-update-mode': { update_mode: 'hour' },
  '/api/governance/conventions/ODS': { layer: 'ODS', rules: { table_prefix: 'ods_' } },
  '/api/governance/conventions/DWD': { layer: 'DWD', rules: { table_prefix: 'dwd_' } },
  '/api/governance/conventions/DWS': { layer: 'DWS', rules: { table_prefix: 'dws_' } },
  '/api/governance/conventions/DMR': { layer: 'DMR', rules: { table_prefix: 'dmr_' } },
  '/api/governance/conventions/DIM': { status: 'ok', layer: 'DIM', data: { layer: 'DIM', naming: { table_prefix: 'dim_' } } },

  '/api/roots/check': {
    passed: true,
    valid_fields: ['order_id', 'order_amt'],
    invalid_fields: ['bad_xyz_foo'],
  },

  '/api/lineage/upstream/dwd_test': { table: 'dwd_test', upstream: [], cached: false },
  '/api/lineage/downstream/dwd_test': { table: 'dwd_test', downstream: [], total: 0 },
  '/api/lineage/graph/dwd_test': { nodes: [], edges: [], cycles: [] },

  '/api/import/preview': {
    total_files: 2,
    total_tables: 3,
    by_layer: { DIM: 3 },
    tables: [
      { table: 'dim_ord_ofc_cancel_reason_all', layer: 'DIM', update_method: 'all', partitions: ['dt'], file: 'dim_ord_ofc_oms_all_ddl.sql' },
      { table: 'dim_ord_oms_platform_all', layer: 'DIM', update_method: 'all', partitions: ['dt'], file: 'dim_ord_ofc_oms_all_ddl.sql' },
      { table: 'dim_ord_oms_payment_all', layer: 'DIM', update_method: 'all', partitions: ['dt'], file: 'dim_ord_ofc_oms_all_ddl.sql' },
    ],
  },

  '/api/sync/tables': { tables: [{ table_name: 'dwd_test', layer: 'DWD', dev_ddl: 'CREATE TABLE...', prod_ddl: 'CREATE TABLE...' }] },
  '/api/sync/history': { jobs: [] },

  '/api/modeling/tasks': {
    tasks: [
      { task_id: 'task_aaa', status: 'completed', target_table: 'dwd_test', target_layer: 'DWD', created_at: '2026-07-01T10:00:00', duration_seconds: 1.2 },
      { task_id: 'task_bbb', status: 'failed', target_table: 'dwd_test2', target_layer: 'DIM', created_at: '2026-07-01T11:00:00', duration_seconds: 0.5 },
    ],
    total: 2,
  },
  '/api/modeling/preview': { ddl_dev: 'CREATE TABLE dataworks.dwd_test (id STRING) PARTITIONED BY (dt STRING);', ddl_prod: 'CREATE TABLE dataworks.dwd_test (id STRING) PARTITIONED BY (dt STRING);', columns: [{ name: 'id', type: 'STRING' }] },

  '/api/monitor/dashboard': { total_tasks: 2, completed: 1, failed: 1, pending: 0, running: 0, success_rate: 0.5, layer_breakdown: { DWD: 1, DIM: 1 } },

  // Pipeline API
  '/api/pipeline/batches': { batches: [], total: 0 },
  '/api/pipeline/tasks': { tasks: [], total: 0 },

  // Workspace API
  '/api/workspace/datasources': {
    datasources: [
      { id: 1, name: 'dataworks', type: 'odps', description: 'MaxCompute 数据源' },
      { id: 2, name: 'dataworks_holo', type: 'holo', description: 'Hologres 数据源' },
    ],
  },
  '/api/workspace/repository-tree': {
    nodes: [
      { name: '01_ODS', type: 'folder', path: 'dataworks_agent/01_ODS' },
      { name: '02_DWD', type: 'folder', path: 'dataworks_agent/02_DWD' },
    ],
  },

  // Data Integration API
  '/api/workspace/datasource-tables': {
    tables: [
      { name: 'ofc_order', schema: 'ofc', description: '订单表' },
      { name: 'ofc_payment', schema: 'ofc', description: '支付表' },
    ],
  },

  // Artifacts API
  '/api/artifacts': { artifacts: [], total: 0 },

  // Ownership API
  '/api/ownership/dwd_test': { records: [{ table_name: 'dwd_test', business_owner: 'data_team' }] },

  // Bus Matrix API
  '/api/bus-matrix': { matrix: [{ domain: 'ord', dimension: '订单', has_link: true }] },

  // Reconciliation API
  '/api/reconciliation/tasks': { tasks: [], total: 0 },

  // Cookie API
  '/api/cookie/status': { valid: true, health: 'healthy', expires_in: 3600 },
}

const server = http.createServer((req, res) => {
  const url = req.url.split('?')[0]  // 去 query

  // POST 端点用简单规则
  if (req.method === 'POST') {
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', () => {
      // 模拟的 task 创建
      if (url === '/api/modeling/tasks') {
        return OK(res, { task_id: 'task_e2e_' + Date.now(), status: 'pending' })
      }
      if (url === '/api/sync/diff' || url === '/api/sync/execute') {
        return OK(res, { has_changes: false, alter_sql: '' })
      }
      if (url === '/api/import/import') {
        return OK(res, { total_files: 0, total_tables: 0, created: 0, failed: 0, details: [] })
      }
      if (url === '/api/governance/check-ddl') {
        return OK(res, MOCKS['/api/governance/check-ddl'])
      }
      if (url === '/api/governance/parse-sql-lineage') {
        return OK(res, MOCKS['/api/governance/parse-sql-lineage'])
      }
      if (url === '/api/governance/parse-table-name') {
        return OK(res, MOCKS['/api/governance/parse-table-name'])
      }
      if (url === '/api/governance/infer-update-mode') {
        return OK(res, MOCKS['/api/governance/infer-update-mode'])
      }
      if (url === '/api/governance/word-roots/sync') {
        return OK(res, {
          status: 'ok',
          count: 1011,
          refreshed_at: '2026-07-09T12:00:00Z',
          source: 'online',
          table: 'dataworks.dim_pub_column_dictionary_static',
        })
      }
      if (url === '/agent/chat') {
        return OK(res, {
          success: true,
          message: '真实问数完成，返回 2 行。',
          data: {
            workflow_type: 'ask_data',
            execution_mode: 'dev_execute',
            agent_mode: 'executed',
            plan: { summary: '今日各家族有效订单数', steps: [
              { step: 'generate_readonly_sql', status: 'completed' },
              { step: 'execute_query', status: 'completed' },
            ] },
            artifacts: [{ type: 'query_sql', content: 'SELECT family_name, effective_order_cnt FROM sample' }],
            query: {
              executed: true,
              execution_channel: 'cookie_bff',
              columns: ['family_name', 'effective_order_cnt'],
              rows: [['吉喵云', '6560'], ['神龙家族', '4015']],
              row_count: 2,
            },
          },
          error: null,
        })
      }
      // POST 兜底 — 404，避免 E2E 测试盲区（与 GET 兜底保持一致）
      return NOT_MOCKED(res, url)
    })
    return
  }

  if (url === '/agent/capabilities') {
    return OK(res, { capabilities: {
      ak_sk: true, openapi: true, maxcompute: true, node_adapter: true,
      cookie_bff: true, cdp_9222: true, cookie_health: 'degraded',
      official_mcp: { enabled: true, connected: true, tool_count: 20 },
    } })
  }

  // GET 查表
  if (MOCKS[url] !== undefined) {
    return OK(res, MOCKS[url])
  }

  // 动态 GET
  if (url.startsWith('/api/governance/conventions/')) {
    return OK(res, { error: 'not found' })
  }

  // 兜底 — 404 (未 mock 的接口返回 404，避免测试盲区)
  res.writeHead(404, { 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify({ error: 'not mocked', url }))
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[fake-bff] listening on http://127.0.0.1:${PORT}`)
})
