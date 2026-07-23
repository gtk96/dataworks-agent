import type { Effect } from "effect"

// Tagged error types — each maps to one HTTP status code in the API layer.
export type DataWorksError =
  | { _tag: "Unauthorized"; message: string }
  | { _tag: "Forbidden"; message: string }
  | { _tag: "RateLimited"; retryAfterMs: number; message: string }
  | { _tag: "NotFound"; message: string }
  | { _tag: "UpstreamUnavailable"; message: string }
  | { _tag: "InvalidResponse"; message: string }

// Domain types — sanitized fixtures only; never include credential material.
export interface Project {
  readonly id: number
  readonly name: string
  readonly envType: string
  readonly region: string
}

export interface Job {
  readonly id: number
  readonly name: string
  readonly projectId: number
  readonly status: string
  /** Instance id when the row comes from ListInstances (required for restartInstance / rerun). */
  readonly instanceId?: number
  /** Node / schedule id (used for supplement + pause; never pass as restartInstance id). */
  readonly nodeId?: number
}

export interface JobStatus {
  readonly id: number
  readonly status: string
  readonly lastRunTime?: number
}

export interface Lineage {
  readonly tableName: string
  readonly upstream: ReadonlyArray<{ name: string; type: string }>
  readonly downstream: ReadonlyArray<{ name: string; type: string }>
}

export interface ProjectPage {
  readonly items: ReadonlyArray<Project>
  readonly total: number
  readonly pageNumber: number
  readonly pageSize: number
}

export interface JobPage {
  readonly items: ReadonlyArray<Job>
  readonly total: number
  readonly pageNumber: number
  readonly pageSize: number
}

export interface Table {
  readonly name: string
  readonly schema?: string
  readonly projectId?: number
  readonly projectName?: string
  readonly tableGuid?: string
  readonly type?: string
  readonly partition?: string
}

export interface TablePage {
  readonly items: ReadonlyArray<Table>
  readonly total: number
  readonly pageNumber: number
  readonly pageSize: number
}

export interface TableColumn {
  readonly name: string
  readonly type: string
  readonly comment?: string
  readonly isPartition?: boolean
  readonly isPrimaryKey?: boolean
}

export interface TableDescription {
  readonly name: string
  readonly schema?: string
  readonly projectName?: string
  readonly tableGuid?: string
  readonly comment?: string
  readonly isPartitionTable?: boolean
  readonly partition?: string
  readonly columns: ReadonlyArray<TableColumn>
}

export interface DataWorksClient {
  listProjects(input: { region: string; pageNumber: number; pageSize: number }): Effect.Effect<ProjectPage, DataWorksError>
  listJobs(input: { projectID: number; pageNumber: number; pageSize: number }): Effect.Effect<JobPage, DataWorksError>
  getJobStatus(input: { projectID: number; instanceID: number }): Effect.Effect<JobStatus, DataWorksError>
  tableLineage(input: { projectID: number; tableName: string }): Effect.Effect<Lineage, DataWorksError>
  listTables(input: {
    projectID: number
    keyword?: string
    pageNumber: number
    pageSize: number
    projectName?: string
  }): Effect.Effect<TablePage, DataWorksError>
  describeTable(input: {
    projectID: number
    tableName: string
    projectName?: string
  }): Effect.Effect<TableDescription, DataWorksError>
}

export const DataWorksError = {
  Unauthorized: (message = "unauthorized"): DataWorksError => ({ _tag: "Unauthorized", message }),
  Forbidden: (message = "forbidden"): DataWorksError => ({ _tag: "Forbidden", message }),
  RateLimited: (retryAfterMs: number, message = "rate limited"): DataWorksError => ({
    _tag: "RateLimited",
    retryAfterMs,
    message,
  }),
  NotFound: (message = "not found"): DataWorksError => ({ _tag: "NotFound", message }),
  UpstreamUnavailable: (message = "upstream unavailable"): DataWorksError => ({
    _tag: "UpstreamUnavailable",
    message,
  }),
  InvalidResponse: (message = "invalid response"): DataWorksError => ({ _tag: "InvalidResponse", message }),
} as const
