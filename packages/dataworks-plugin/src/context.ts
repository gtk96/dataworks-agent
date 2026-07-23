import type { ToolContext } from "@opencode-ai/plugin"
import { client } from "./client.js"

export interface PluginContext {
  readonly tool: ToolContext
}

export { client }