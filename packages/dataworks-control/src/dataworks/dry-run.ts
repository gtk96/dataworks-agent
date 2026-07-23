import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import * as Eff from "effect/Effect"
import type {
  DataWorksClient,
  DataWorksError,
  Job,
  JobPage,
  JobStatus,
  Lineage,
  Project,
  ProjectPage,
  Table,
  TableDescription,
  TablePage,
} from "@dataworks-agent/core"

interface ProjectsFixture {
  readonly projects: ReadonlyArray<Project>
  readonly lineage: Record<string, Lineage>
}

interface JobsFixture {
  readonly jobs: ReadonlyArray<Job>
  readonly jobStatus: Record<string, JobStatus>
}

interface TablesFixture {
  readonly tables: ReadonlyArray<Table>
  readonly descriptions: Record<string, TableDescription>
}

function fixturePath(filename: string): string {
  const here = dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"))
  // dry-run.ts lives at <root>/packages/dataworks-control/src/dataworks/dry-run.ts
  // We need <root>/tests/fixtures/dataworks/<file>.
  return join(here, "..", "..", "..", "..", "tests", "fixtures", "dataworks", filename)
}

function loadProjects(): ProjectsFixture {
  const raw = readFileSync(fixturePath("projects.json"), "utf-8")
  const parsed = JSON.parse(raw) as { projects: Project[]; lineage: Record<string, Lineage> }
  return { projects: parsed.projects, lineage: parsed.lineage }
}

function loadJobs(): JobsFixture {
  const raw = readFileSync(fixturePath("jobs.json"), "utf-8")
  const parsed = JSON.parse(raw) as { jobs: Job[]; jobStatus: Record<string, JobStatus> }
  return { jobs: parsed.jobs, jobStatus: parsed.jobStatus }
}

function loadTables(): TablesFixture {
  const raw = readFileSync(fixturePath("tables.json"), "utf-8")
  const parsed = JSON.parse(raw) as {
    tables: Table[]
    descriptions: Record<string, TableDescription>
  }
  return { tables: parsed.tables, descriptions: parsed.descriptions }
}

function pageSlice<T>(items: ReadonlyArray<T>, pageNumber: number, pageSize: number): {
  items: ReadonlyArray<T>
  total: number
  pageNumber: number
  pageSize: number
} {
  const start = (pageNumber - 1) * pageSize
  return {
    items: items.slice(start, start + pageSize),
    total: items.length,
    pageNumber,
    pageSize,
  }
}

export class DryRunDataWorksClient implements DataWorksClient {
  private readonly projects: ProjectsFixture
  private readonly jobs: JobsFixture
  private readonly tables: TablesFixture

  constructor() {
    this.projects = loadProjects()
    this.jobs = loadJobs()
    this.tables = loadTables()
  }

  listProjects(input: { region: string; pageNumber: number; pageSize: number }) {
    // Prefer region match; if none, return all fixtures so local demos with
    // e.g. cn-shenzhen connections still get a usable project list.
    const byRegion = this.projects.projects.filter((p) => p.region === input.region)
    const source = byRegion.length > 0 ? byRegion : this.projects.projects
    const adapted =
      byRegion.length > 0
        ? source
        : source.map((p) => ({ ...p, region: input.region || p.region }))
    const page = pageSlice(adapted, input.pageNumber, input.pageSize)
    return Eff.succeed(page)
  }

  listJobs(input: { projectID: number; pageNumber: number; pageSize: number }) {
    const filtered = this.jobs.jobs.filter((j) => j.projectId === input.projectID)
    const page = pageSlice(filtered, input.pageNumber, input.pageSize)
    return Eff.succeed(page)
  }

  getJobStatus(input: { projectID: number; instanceID: number }) {
    const status = this.jobs.jobStatus[String(input.instanceID)]
    if (!status) {
      return Eff.fail({
        _tag: "NotFound",
        message: `job ${input.instanceID} not found`,
      } as DataWorksError)
    }
    return Eff.succeed(status)
  }

  tableLineage(input: { projectID: number; tableName: string }) {
    const lineage = this.projects.lineage[input.tableName]
    if (!lineage) {
      return Eff.fail({
        _tag: "NotFound",
        message: `lineage for ${input.tableName} not found`,
      } as DataWorksError)
    }
    return Eff.succeed(lineage)
  }

  listTables(input: {
    projectID: number
    keyword?: string
    pageNumber: number
    pageSize: number
    projectName?: string
  }) {
    const kw = (input.keyword ?? "").trim().toLowerCase()
    const filtered = this.tables.tables.filter((t) => {
      if (t.projectId !== undefined && t.projectId !== input.projectID) return false
      if (!kw) return true
      return t.name.toLowerCase().includes(kw) || (t.schema ?? "").toLowerCase().includes(kw)
    })
    const page = pageSlice(filtered, input.pageNumber, input.pageSize)
    return Eff.succeed(page as TablePage)
  }

  describeTable(input: { projectID: number; tableName: string; projectName?: string }) {
    void input.projectID
    void input.projectName
    const desc = this.tables.descriptions[input.tableName]
    if (!desc) {
      return Eff.fail({
        _tag: "NotFound",
        message: `table ${input.tableName} not found`,
      } as DataWorksError)
    }
    return Eff.succeed(desc)
  }
}
