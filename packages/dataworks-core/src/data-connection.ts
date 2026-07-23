export type DataConnectionRegion = string

export interface DataConnectionSecret {
  readonly access_key_id: string
  readonly access_key_secret: string
}

export interface DataConnectionCreateInput {
  readonly name: string
  readonly region: DataConnectionRegion
  readonly access_key_id: string
  readonly access_key_secret: string
  readonly write_enabled: boolean
}

export interface DataConnectionMetadata {
  readonly id: string
  readonly user_id: string
  readonly name: string
  readonly region: DataConnectionRegion
  readonly access_key_display: string
  readonly write_enabled: boolean
  readonly time_created: number
  readonly time_updated: number
}

export function maskAccessKeyId(accessKeyId: string): string {
  if (accessKeyId.length <= 10) return "***"
  const head = accessKeyId.slice(0, 6)
  const tail = accessKeyId.slice(-4)
  return `${head}***${tail}`
}

export const DataConnection = {
  maskAccessKeyId,
}
