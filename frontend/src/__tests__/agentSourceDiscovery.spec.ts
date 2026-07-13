import { describe, expect, it } from 'vitest'
import { buildSourceDiscoveryView } from '@/components/agent/sourceDiscovery'

describe('Agent OSS source discovery', () => {
  it('builds success evidence without exposing sample content', () => {
    const view = buildSourceDiscoveryView({
      success: true,
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
})
