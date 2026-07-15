export type ExecutionResourceRow = Record<string, unknown>

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return ''
}

function tableText(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (!value || typeof value !== 'object') return ''
  const item = value as ExecutionResourceRow
  const table = firstText(item.qualified_table, item.table, item.table_name, item.name)
  if (table.includes('.') || !table) return table
  const schema = firstText(item.schema, item.project)
  return schema ? `${schema}.${table}` : table
}

function addResource(resources: string[], value: unknown): void {
  if (typeof value !== 'string' || !value.trim()) return
  const normalized = value.trim()
  if (!resources.includes(normalized)) resources.push(normalized)
}

function pipelineResource(label: string, pipeline: unknown): string {
  if (!pipeline || typeof pipeline !== 'object') return ''
  const item = pipeline as ExecutionResourceRow
  if (item.success === false) return ''
  const steps = item.steps && typeof item.steps === 'object' ? item.steps as ExecutionResourceRow : undefined
  const createNode = steps?.create_node && typeof steps.create_node === 'object'
    ? steps.create_node as ExecutionResourceRow
    : undefined
  const node = firstText(
    item.node_path,
    item.node_name,
    item.path,
    createNode?.path,
    item.node_uuid,
    item.uuid,
    createNode?.uuid,
  )
  return node ? `${label} 节点: ${node}` : ''
}

/**
 * Returns the resources created by the latest execution for the result summary.
 * Generic workflows expose `executed`; the standard OSS workflow exposes the
 * repository-owned `dev_tables` and pipeline node metadata instead.
 */
export function buildExecutionResources(data?: Record<string, unknown>): string[] {
  if (!data) return []

  const resources: string[] = []
  const executed = Array.isArray(data.executed) ? data.executed : []
  for (const row of executed) {
    if (!row || typeof row !== 'object') continue
    const item = row as ExecutionResourceRow
    addResource(resources, firstText(item.table, item.node_name, item.nodeName, item.name))
  }
  if (resources.length) return resources

  const devTables = data.dev_tables && typeof data.dev_tables === 'object'
    ? data.dev_tables as ExecutionResourceRow
    : undefined
  for (const layer of ['ods', 'dwd']) {
    const table = tableText(devTables?.[layer])
    if (table) addResource(resources, `${layer.toUpperCase()} 表: ${table}`)
  }

  for (const [key, label] of [['ods_pipeline', 'ODS'], ['dwd_pipeline', 'DWD']]) {
    addResource(resources, pipelineResource(label, data[key]))
  }

  return resources
}
