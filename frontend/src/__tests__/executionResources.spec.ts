import { describe, expect, it } from 'vitest'
import { buildExecutionResources } from '@/components/agent/executionResources'

describe('Agent execution resource summary', () => {
  it('keeps generic executed resources unchanged', () => {
    expect(buildExecutionResources({
      executed: [
        { table: 'giikin_develop.ods_orders' },
        { node_name: 'dwd_orders_node' },
      ],
      dev_tables: { ods: 'should-not-be-used' },
    })).toEqual(['giikin_develop.ods_orders', 'dwd_orders_node'])
  })

  it('shows standard OSS dev tables and both pipeline nodes', () => {
    expect(buildExecutionResources({
      dev_tables: {
        ods: 'giikin_develop.ods_mc_ads_data__tiktok_smart_plus_material_report_hour',
        dwd: 'giikin_develop.dwd_mkt_tiktok_smart_plus_material_report_hour',
      },
      ods_pipeline: { success: true, node_uuid: 'ods-node-1', node_path: '业务流程/00_ODS/ods_node' },
      dwd_pipeline: { success: true, node_uuid: 'dwd-node-1', node_path: '业务流程/02_DWD/dwd_node' },
    })).toEqual([
      'ODS 表: giikin_develop.ods_mc_ads_data__tiktok_smart_plus_material_report_hour',
      'DWD 表: giikin_develop.dwd_mkt_tiktok_smart_plus_material_report_hour',
      'ODS 节点: 业务流程/00_ODS/ods_node',
      'DWD 节点: 业务流程/02_DWD/dwd_node',
    ])
  })

  it('ignores failed or duplicate pipeline metadata', () => {
    expect(buildExecutionResources({
      dev_tables: {
        ods: { status: 'skipped', schema: 'giikin_develop', table: 'ods_orders' },
        dwd: { status: 'skipped', schema: 'giikin_develop', table: 'ods_orders' },
      },
      ods_pipeline: { success: false, node_uuid: 'failed' },
      dwd_pipeline: { success: true, node_uuid: 'giikin_develop.ods_orders' },
    })).toEqual([
      'ODS 表: giikin_develop.ods_orders',
      'DWD 表: giikin_develop.ods_orders',
      'DWD 节点: giikin_develop.ods_orders',
    ])
  })
})

