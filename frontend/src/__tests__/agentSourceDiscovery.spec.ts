import { describe, expect, it } from 'vitest'
import { buildSourceDiscoveryView } from '@/components/agent/sourceDiscovery'

describe('Agent OSS source discovery', () => {
  it('builds success evidence without exposing sample content', () => {
    const view = buildSourceDiscoveryView({
      success: true,
      channel: 'local_oss_sdk',
      location: {
        endpoint: 'oss-cn-shenzhen-internal.aliyuncs.com',
        bucket: 'bucket-name',
        object_key: 'ads/report',
      },
      endpoint_used: 'oss-cn-shenzhen.aliyuncs.com',
      attempted_endpoints: [
        'oss-cn-shenzhen-internal.aliyuncs.com',
        'oss-cn-shenzhen.aliyuncs.com',
      ],
      file_format: 'json',
      sample_object: 'ads/report/part-000.jsonl',
      record_count: 20,
      columns: [{ name: 'id', type: 'BIGINT' }],
    })

    expect(view).toMatchObject({
      visible: true,
      success: true,
      statusText: '探测完成',
      channelText: '本地 OSS SDK',
      showEndpoint: true,
      endpointUsed: 'oss-cn-shenzhen.aliyuncs.com',
      bucket: 'bucket-name',
      prefix: 'ads/report',
      fileFormat: 'JSON',
      recordCount: 20,
      columnCount: 1,
    })
    expect(view).not.toHaveProperty('sample_content')
  })

  it('keeps an actionable permission failure', () => {
    const view = buildSourceDiscoveryView({
      success: false,
      location: { bucket: 'bucket-name', object_key: 'ads/report' },
      error_code: 'accessdenied',
      error: 'AccessDenied',
      next_action: '授予最小读权限',
    })

    expect(view.statusText).toBe('需要处理')
    expect(view.errorCode).toBe('accessdenied')
    expect(view.nextAction).toBe('授予最小读权限')
    expect(view.columnCount).toBe(0)
  })

  it('shows managed datasource evidence without local endpoint emphasis', () => {
    const view = buildSourceDiscoveryView({
      success: true,
      channel: 'dataworks_managed_datasource',
      datasource_name: 'managed_oss',
      metadata_source: 'registered_external_table',
      ingestion_mode: 'raw_json_text',
      location: { bucket: 'bucket-name', object_key: 'ads/report' },
      file_format: 'json',
      columns: [{ name: 'json_data', type: 'STRING' }],
    })

    expect(view).toMatchObject({
      channelText: 'DataWorks 托管数据源',
      datasourceName: 'managed_oss',
      metadataSourceText: '已注册外部表 DDL',
      ingestionMode: 'raw_json_text',
      showEndpoint: false,
      columnCount: 1,
    })
    expect(view).not.toHaveProperty('sample_content')
  })
})
