import type { Plugin, ToolDefinition } from "@opencode-ai/plugin"
import { dw_list_projects } from "./tools/projects.js"
import { dw_list_tables, dw_describe_table } from "./tools/tables.js"
import { dw_run_sql } from "./tools/sql.js"
import { dw_list_jobs, dw_get_job_status } from "./tools/jobs.js"
import { dw_table_lineage, dw_alert_list, dw_mcp_call } from "./tools/lineage.js"
import { dw_rerun_job, dw_trigger_supplement, dw_pause_schedule, dw_alert_silence } from "./tools/write.js"
import { dw_knowledge_search, searchKnowledge } from "./tools/knowledge.js"
import { formatSkillGateOutput, getSkillContext } from "./skill-context.js"
import {
  buildRagSystemContext,
  createRagSystemTransform,
  type RagChunk,
} from "./rag-context.js"

/** Tool map registered on the OpenCode plugin Hooks.tool surface. */
export function dataworksPlugin(): Record<string, ToolDefinition> {
  return {
    dw_list_projects,
    dw_list_tables,
    dw_describe_table,
    dw_run_sql,
    dw_table_lineage,
    dw_list_jobs,
    dw_get_job_status,
    dw_alert_list,
    dw_mcp_call,
    dw_rerun_job,
    dw_trigger_supplement,
    dw_pause_schedule,
    dw_alert_silence,
    dw_knowledge_search,
  }
}

type KnowledgeBaseEnv = {
  egressPolicy: "local_only" | "approved_providers"
  approvedProviders: string[]
  id: string
  name: string
}

function parseKnowledgeBaseEnv(): KnowledgeBaseEnv | null {
  const kbRaw = process.env.DWA_ACTIVE_KNOWLEDGE_BASE
  if (!kbRaw) return null
  try {
    return JSON.parse(kbRaw) as KnowledgeBaseEnv
  } catch {
    return null
  }
}

function parseEnvChunks(): RagChunk[] {
  const chunksRaw = process.env.DWA_RAG_CHUNKS
  if (!chunksRaw) return []
  try {
    return JSON.parse(chunksRaw) as RagChunk[]
  } catch {
    return []
  }
}

function extractUserText(parts: ReadonlyArray<{ type?: string; text?: string }> | undefined): string {
  if (!parts?.length) return ""
  return parts
    .filter((p) => p && (p.type === "text" || p.type === undefined) && typeof p.text === "string")
    .map((p) => p.text!.trim())
    .filter(Boolean)
    .join("\n")
}

/**
 * OpenCode plugin entrypoint. Loaded via managed/user config:
 * `{ "plugin": ["@dataworks-agent/plugin"] }`
 * — never by patching packages/opencode/src/tool/registry.ts.
 *
 * Hooks enforce Skill frontmatter policy (forbidden/allowed/write/max calls)
 * and track active skill loads from the OpenCode `skill` tool.
 * experimental.chat.system.transform injects tenant-scoped RAG citations when allowed:
 * live retrieve via internal knowledge search when DWA + control-plane env present,
 * otherwise optional DWA_RAG_CHUNKS injection. Missing control plane is non-fatal.
 */
export const DataworksPlugin: Plugin = async () => {
  const skillCtx = getSkillContext()
  /** Last user message text per session for RAG query. */
  const sessionQueries = new Map<string, string>()
  let transformSessionID = ""
  let transformProvider = ""

  const ragTransform = createRagSystemTransform({
    getActiveProvider: () =>
      transformProvider || process.env.DWA_ACTIVE_PROVIDER?.trim() || "",
    getKnowledgeBase: () => parseKnowledgeBaseEnv(),
    getQuery: () => {
      if (transformSessionID) {
        const q = sessionQueries.get(transformSessionID)
        if (q?.trim()) return q
      }
      return process.env.DWA_RAG_QUERY?.trim() || ""
    },
    retrieve: async (query, _provider) => {
      const kb = parseKnowledgeBaseEnv()
      if (!kb?.id || !query.trim()) return []
      try {
        const hits = await searchKnowledge({
          knowledgeBaseId: kb.id,
          query,
          topK: 5,
        })
        return hits.map(
          (h): RagChunk => ({
            text: h.text,
            citation: h.citation,
            score: h.score,
            filename: h.filename,
            documentId: h.documentId,
          }),
        )
      } catch {
        // Dry-run / missing control plane / network — non-fatal.
        return []
      }
    },
  })

  return {
    tool: dataworksPlugin(),
    "chat.message": async (input, output) => {
      const text = extractUserText(
        output.parts as ReadonlyArray<{ type?: string; text?: string }> | undefined,
      )
      if (text && input.sessionID) {
        sessionQueries.set(input.sessionID, text)
      }
    },
    "tool.execute.before": async (input, _output) => {
      if (input.tool === "skill") {
        const name = typeof _output.args?.name === "string" ? _output.args.name : undefined
        if (name) skillCtx.setActiveSkill(input.sessionID, name)
        return
      }

      if (!input.tool.startsWith("dw_")) return

      const gate = skillCtx.gateTool({
        sessionID: input.sessionID,
        tool: input.tool,
      })
      if (gate._tag === "ok" || gate._tag === "no_active_skill") return

      const err = new Error(formatSkillGateOutput(gate))
      ;(err as Error & { skillGate: typeof gate }).skillGate = gate
      throw err
    },
    "experimental.chat.system.transform": async (input, output) => {
      const model = (input as { model?: { providerID?: string; provider?: string } }).model
      transformProvider =
        model?.providerID ?? model?.provider ?? process.env.DWA_ACTIVE_PROVIDER ?? ""
      transformSessionID = (input as { sessionID?: string }).sessionID ?? ""

      // Live retrieve path (createRagSystemTransform + internal search). Non-fatal.
      try {
        await ragTransform(
          { system: output.system, model: model as { providerID?: string; provider?: string } },
          output,
        )
      } catch {
        // Keep chat usable without control plane.
      }

      // Env-chunk fallback when no live injection (tests / pre-seeded chunks).
      const alreadyInjected = (output.system ?? []).some((s) =>
        s.includes("Retrieved knowledge-base context"),
      )
      if (alreadyInjected) return

      const kb = parseKnowledgeBaseEnv()
      const provider = transformProvider
      if (!kb || !provider) return
      const chunks = parseEnvChunks()
      if (chunks.length === 0) return
      const built = buildRagSystemContext({
        knowledgeBase: kb,
        activeProvider: provider,
        chunks,
      })
      if (!built.allowed || !built.systemText) return
      const system = output.system ?? (input as { system?: string[] }).system ?? []
      output.system = [...system, built.systemText]
    },
  }
}

export default DataworksPlugin

export { client } from "./client.js"
export { ControlPlaneClient, ControlPlaneError } from "./client.js"
export { askDwWrite, writeArgsHash, WritePermissionDeniedError } from "./permission.js"
export {
  dw_rerun_job,
  dw_trigger_supplement,
  dw_pause_schedule,
  dw_alert_silence,
} from "./tools/write.js"
export {
  SkillContext,
  getSkillContext,
  resetSkillContext,
  resolveRoots,
  formatSkillGateOutput,
} from "./skill-context.js"
export {
  buildRagSystemContext,
  createRagSystemTransform,
  formatSearchToolOutput,
  MAX_RAG_CONTEXT_TOKENS,
} from "./rag-context.js"
export { dw_knowledge_search, searchKnowledge } from "./tools/knowledge.js"
