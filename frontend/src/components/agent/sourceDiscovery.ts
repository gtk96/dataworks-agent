export interface SourceDiscoveryView {
  visible: boolean
  success: boolean
  statusText: string
  channel: string
  channelText: string
  datasourceName: string
  metadataSource: string
  metadataSourceText: string
  ingestionMode: string
  showEndpoint: boolean
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

const CHANNEL_TEXT: Record<string, string> = {
  dataworks_managed_datasource: 'DataWorks 托管数据源',
  local_oss_sdk: '本地 OSS SDK',
  explicit_columns: '显式字段',
  existing_target_table: '已有目标表',
  managed_then_local: '托管 + 本地后备',
}

const METADATA_SOURCE_TEXT: Record<string, string> = {
  registered_external_table: '已注册外部表 DDL',
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
  const channel = String(source.channel || source.source || '')
  const metadataSource = String(source.metadata_source || '')
  return {
    visible,
    success,
    statusText: success ? '探测完成' : '需要处理',
    channel,
    channelText: CHANNEL_TEXT[channel] || channel || '未确定',
    datasourceName: String(source.datasource_name || ''),
    metadataSource,
    metadataSourceText: METADATA_SOURCE_TEXT[metadataSource] || metadataSource || '',
    ingestionMode: String(source.ingestion_mode || ''),
    showEndpoint: channel === 'local_oss_sdk' || attemptedEndpoints.length > 0,
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
