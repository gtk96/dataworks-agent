export type ProductMode = "staging" | "production" | "development"

export class DryRunForbiddenError extends Error {
  readonly code = "DRY_RUN_FORBIDDEN" as const

  constructor(
    message = "Product mode forbids DATAWORKS_AGENT_DRY_RUN. Unset it or set DATAWORKS_AGENT_DRY_RUN=0 to start the control plane.",
  ) {
    super(message)
    this.name = "DryRunForbiddenError"
  }
}

function isTruthyDryRun(value: string | undefined): boolean {
  if (value === undefined || value === "") return false
  const normalized = value.trim().toLowerCase()
  return normalized === "1" || normalized === "true" || normalized === "yes"
}

/** Refuse product start / acceptance when dry-run is explicitly enabled. */
export function assertProductDryRunAllowed(
  env: Record<string, string | undefined> = process.env as Record<string, string | undefined>,
): void {
  if (isTruthyDryRun(env.DATAWORKS_AGENT_DRY_RUN)) {
    throw new DryRunForbiddenError()
  }
}

/**
 * Resolve product mode for start / acceptance.
 * Throws DryRunForbiddenError when DATAWORKS_AGENT_DRY_RUN ∈ {1,true,yes}.
 */
export function readProductMode(
  env: Record<string, string | undefined> = process.env as Record<string, string | undefined>,
): ProductMode {
  assertProductDryRunAllowed(env)

  const raw = (env.DATAWORKS_AGENT_ENV ?? env.NODE_ENV ?? "development").trim().toLowerCase()
  if (raw === "production" || raw === "prod") return "production"
  if (raw === "staging" || raw === "stage") return "staging"
  if (raw === "development" || raw === "dev" || raw === "single-user-dev") return "development"
  return "development"
}
