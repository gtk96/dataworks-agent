export interface SourceDiscoveryView {
  visible: boolean
  success: boolean
  statusText: string
  endpoint: string
  endpointUsed: string
  attemptedEndpoints: string[]
  bucket: string
  prefix: string
  fileFormat: string
  sampleObject: string
  recordCount: number
  columnCount: number
  errorCode: string
  error: string
  nextAction: string
}

export function buildSourceDiscoveryView(value: unknown): SourceDiscoveryView {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const location = source.location && typeof source.location === 'object'
    ? source.location as Record<string, unknown>
    : {}
  const columns = Array.isArray(source.columns) ? source.columns : []
  const attemptedEndpoints = Array.isArray(source.attempted_endpoints)
    ? source.attempted_endpoints.map(String).filter(Boolean)
    : []
  const visible = Object.keys(source).length > 0
  const success = source.success === true
  return {
    visible,
    success,
    statusText: success ? '探测完成' : '需要处理',
    endpoint: String(location.endpoint || '按地域自动选择'),
    endpointUsed: String(source.endpoint_used || ''),
    attemptedEndpoints,
    bucket: String(location.bucket || '?'),
    prefix: String(location.object_key || '根目录'),
    fileFormat: String(source.file_format || '未确定').toUpperCase(),
    sampleObject: String(source.sample_object || ''),
    recordCount: Number(source.record_count || 0),
    columnCount: columns.length,
    errorCode: String(source.error_code || ''),
    error: String(source.error || ''),
    nextAction: String(source.next_action || ''),
  }
}
