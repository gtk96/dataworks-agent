export interface AgentStepLike {
  status?: string
}

const COMPLETED = new Set(['completed', 'success', 'done', 'ok'])
const PLANNED = new Set(['planned', 'pending', 'required_only_for_publish'])

export function summarizeAgentSteps(steps: AgentStepLike[]) {
  let completed = 0
  let planned = 0
  let warning = 0
  let failed = 0
  for (const step of steps) {
    const status = String(step.status ?? '').toLowerCase()
    if (COMPLETED.has(status)) completed += 1
    else if (PLANNED.has(status)) planned += 1
    else if (status === 'warning' || status === 'skipped' || status === 'approval_required') warning += 1
    else if (status === 'failed' || status === 'error' || status === 'blocked') failed += 1
  }
  return { completed, planned, warning, failed, total: steps.length }
}

export function agentStepMarker(step: AgentStepLike, index: number): string {
  const status = String(step.status ?? '').toLowerCase()
  if (COMPLETED.has(status)) return '✓'
  if (status === 'failed' || status === 'error' || status === 'blocked') return '!'
  if (status === 'warning') return '△'
  if (status === 'skipped') return '–'
  if (status === 'approval_required') return '审'
  return String(index + 1)
}
