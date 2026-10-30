/** Explicitly fictional UI preview; never exported as a real execution or test result. */
import type { AgentId, Mission, MissionEvent, Phase } from '../lib/types'

const sampleChanges = [{
  path: 'mini_shop/pricing.py',
  before: 'def apply_coupon(total, code):\n    discount = COUPONS[code]\n    return round(total * (1 - discount), 2)',
  after: 'def apply_coupon(total, code):\n    rate = COUPONS.get(code.upper())\n    if rate is None:\n        raise ValueError("Unknown coupon")\n    discounted = total * (1 - rate)\n    return max(Decimal("0"), discounted)',
}]

export function createPreview(request = 'Add coupon support. SAVE10 gives 10% off.', repository = 'mini_shop'): Mission {
  return {
    id: 'preview-mission', request, repository, phase: 'planning', activeAgent: 'planner', source: 'preview',
    events: [], changes: [], tests: [], issues: [], approvalEligible: false,
    criteria: [
      { id: 'AC-01', text: 'SAVE10 applies a 10% discount', status: 'pending' },
      { id: 'AC-02', text: 'Cart totals never fall below zero', status: 'pending' },
      { id: 'AC-03', text: 'Existing cart behavior is preserved', status: 'pending' },
    ],
  }
}

export const PREVIEW_STORY: { phase: Phase; agent: AgentId; type: string; summary: string; tool?: string; output?: string }[] = [
  { phase: 'planning', agent: 'master', type: 'HANDOFF', summary: 'Architect, map the request to acceptance criteria.' },
  { phase: 'planning', agent: 'planner', type: 'TOOL_CALL', tool: 'read_file', summary: 'Reading cart.py and repository conventions.' },
  { phase: 'planning', agent: 'planner', type: 'PLAN_READY', summary: 'Three criteria. Two implementation tasks. One clear direction.' },
  { phase: 'building', agent: 'master', type: 'HANDOFF', summary: 'Blueprint ready. Engineer, take it from here.' },
  { phase: 'building', agent: 'developer', type: 'TOOL_CALL', tool: 'edit_file', summary: 'Adding coupon validation and discount calculation.' },
  { phase: 'verifying', agent: 'master', type: 'HANDOFF', summary: 'Verifier, challenge the implementation independently.' },
  { phase: 'verifying', agent: 'verifier', type: 'TEST_FAILURE', tool: 'write_check', summary: 'Edge-case check found a negative cart total.', output: 'PREVIEW ONLY\nIndependent check: large discount\nExpected: total >= 0\nObserved: total < 0\nFinding sent to Engineer.' },
  { phase: 'building', agent: 'master', type: 'RETRY', summary: 'New evidence. Engineer, revise the boundary condition.' },
  { phase: 'building', agent: 'developer', type: 'TOOL_CALL', tool: 'edit_file', summary: 'Clamping discounted totals at zero; preserving precision.' },
  { phase: 'verifying', agent: 'verifier', type: 'PREVIEW_CHECK', summary: 'Preview checks now satisfy the acceptance criteria.', output: 'PREVIEW ONLY\nCoupon calculation · passed\nNegative-total boundary · passed\nExisting cart behavior · passed\nThese are illustrative states, not executed tests.' },
  { phase: 'reviewing', agent: 'master', type: 'HANDOFF', summary: 'Sentinel, inspect the patch and its dependencies.' },
  { phase: 'reviewing', agent: 'reviewer', type: 'REVIEW_ISSUE', tool: 'scan_secrets', summary: 'A planted fake key was found in the imported configuration.' },
  { phase: 'building', agent: 'developer', type: 'TOOL_CALL', tool: 'edit_file', summary: 'Moving payment configuration to environment variables.' },
  { phase: 'reviewing', agent: 'reviewer', type: 'PREVIEW_REVIEW', summary: 'Preview review complete. No unresolved preview findings.' },
  { phase: 'awaiting_human', agent: 'master', type: 'AWAITING_HUMAN', summary: 'The last move is yours. Review the proposed change.' },
]

export function previewStep(mission: Mission, index: number): Mission {
  const step = PREVIEW_STORY[index]
  if (!step || mission.source !== 'preview' || mission.events.some(event => event.id === `preview-${index}`)) return mission
  const event: MissionEvent = { ...step, id: `preview-${index}`, time: new Date().toISOString() }
  const passed = index >= 9
  return {
    ...mission, phase: step.phase, activeAgent: step.agent,
    events: [...mission.events, event].slice(-100),
    changes: index >= 4 ? sampleChanges : [],
    criteria: mission.criteria.map((criterion, i) => ({ ...criterion, status: passed ? 'passed' : index === 6 && i === 1 ? 'failed' : 'pending' })),
    tests: index >= 6 ? [{ command: 'Illustrative independent checks', status: passed ? 'passed' : 'failed', output: PREVIEW_STORY[passed ? 9 : 6].output! }] : [],
    issues: index >= 11 ? [{ id: 'preview-key', text: 'Planted fake payment key in imported config', severity: 'high', status: index >= 13 ? 'resolved' : 'open', file: 'config.py' }] : [],
    approvalEligible: false,
  }
}
