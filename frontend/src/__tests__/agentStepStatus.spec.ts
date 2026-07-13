import { describe, expect, it } from 'vitest'
import { agentStepMarker, summarizeAgentSteps } from '@/components/agent/stepStatus'

describe('Agent step status', () => {
  it('does not count planned steps as completed', () => {
    const summary = summarizeAgentSteps([
      { status: 'planned' },
      { status: 'required_only_for_publish' },
      { status: 'completed' },
      { status: 'needs_context' },
    ])
    expect(summary).toEqual({ completed: 1, planned: 2, warning: 1, failed: 0, total: 4 })
  })

  it('renders markers from each real step status', () => {
    expect(agentStepMarker({ status: 'planned' }, 0)).toBe('1')
    expect(agentStepMarker({ status: 'completed' }, 1)).toBe('✓')
    expect(agentStepMarker({ status: 'warning' }, 2)).toBe('△')
    expect(agentStepMarker({ status: 'failed' }, 3)).toBe('!')
    expect(agentStepMarker({ status: 'skipped' }, 4)).toBe('–')
  })
})
