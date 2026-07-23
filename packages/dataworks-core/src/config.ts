import { Schema } from "effect"

const Info = Schema.Struct({
  dryRun: Schema.Boolean,
  host: Schema.String,
  port: Schema.Number,
  publicRegistration: Schema.Boolean,
  workerIdleSeconds: Schema.Number,
})

function bool(value: string | undefined, fallback: boolean) {
  if (value === undefined) return fallback
  return value === "1" || value.toLowerCase() === "true"
}

export function load(env: Record<string, string | undefined>): typeof Info.Type {
  const dryRun = bool(env.DATAWORKS_AGENT_DRY_RUN, true)
  if (!dryRun && !env.DATAWORKS_AGENT_ENV) throw new Error("DATAWORKS_AGENT_ENV is required when dry-run is disabled")
  return {
    dryRun,
    host: env.HOST ?? "127.0.0.1",
    port: Number(env.PORT ?? 8084),
    publicRegistration: bool(env.DATAWORKS_AGENT_PUBLIC_REGISTRATION, false),
    workerIdleSeconds: Number(env.DATAWORKS_AGENT_WORKER_IDLE_SECONDS ?? 900),
  }
}

export const DataWorksConfig = { Info, load }
