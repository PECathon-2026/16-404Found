/** Contract and approval-boundary checks; fixtures represent tests, never run evidence. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Mission } from './types'
import { canApprove, decideMission, parseRecording, validateMission } from './transport'
import { createPreview, PREVIEW_STORY, previewStep } from '../preview/mission'

function verifiedMission(): Mission {
  return {
    ...createPreview(), id: 'test-run', source: 'live', phase: 'awaiting_human',
    patchHash: 'test-patch-sha', approvalEligible: true,
    criteria: [{ id: 'criterion', text: 'Expected behavior', status: 'passed', evidence: 'Independent check output' }],
    tests: [{ command: 'pytest', status: 'passed', output: 'Fixture output for contract testing' }],
    changes: [{ path: 'example.py', before: 'old', after: 'new' }],
  }
}
afterEach(() => vi.unstubAllGlobals())

describe('approval boundary', () => {
  it('accepts only a live, evidence-backed, identified candidate', () => expect(canApprove(verifiedMission())).toBe(true))
  it.each([
    { source: 'preview' }, { source: 'recording' }, { phase: 'building' },
    { approvalEligible: false }, { patchHash: undefined }, { patchHash: ' ' },
    { criteria: [] }, { tests: [] }, { changes: [] },
    { criteria: [{ id: 'c', text: 'Check', status: 'passed' }] },
    { criteria: [{ id: 'c', text: 'Check', status: 'passed', evidence: ' ' }] },
    { tests: [{ command: 'pytest', status: 'unavailable', output: 'missing' }] },
    { tests: [{ command: 'pytest', status: 'passed', output: '' }] },
    { issues: [{ id: 'i', text: 'Finding', severity: 'high', status: 'open' }] },
  ])('blocks an incomplete or non-live candidate: %j', patch => {
    expect(canApprove({ ...verifiedMission(), ...patch } as Mission)).toBe(false)
  })
  it('never sends preview or recorded decisions to the backend', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch)
    for (const source of ['preview', 'recording'] as const) {
      for (const decision of ['approve', 'reject'] as const) {
        await expect(decideMission('/api', { ...verifiedMission(), source }, decision)).rejects.toThrow('cannot modify')
      }
    }
    expect(fetch).not.toHaveBeenCalled()
  })
  it('submits the reviewed patch identity, and surfaces a stale-patch rejection', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 409 }); vi.stubGlobal('fetch', fetch)
    await expect(decideMission('/api/', verifiedMission(), 'approve')).rejects.toThrow('Refresh the evidence')
    expect(fetch).toHaveBeenCalledWith('/api/missions/test-run/approval', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ decision: 'approve', patch_hash: 'test-patch-sha' }),
    }))
  })
})

describe('backend contract', () => {
  it('ignores a server-provided preview label and derives the active agent when omitted', () => {
    const m = validateMission({ ...verifiedMission(), source: 'preview', phase: 'verifying', activeAgent: undefined })
    expect(m.source).toBe('live'); expect(m.activeAgent).toBe('verifier')
  })
  it.each([
    { events: [{ id: 'e', agent: 'planner', summary: 'Missing type and time' }] },
    { criteria: [{ id: 'c', text: 'Check', status: 'passed', evidence: 42 }] },
    { patchHash: 42 }, { changes: [{ path: 'x', before: null, after: 'x' }] },
    { tests: [{ command: 'pytest', status: 'passed', output: {} }] },
    { issues: [{ id: 'i', text: 'Finding', severity: 'high', status: 'open', file: {} }] },
  ])('rejects malformed evidence: %j', patch => {
    expect(() => validateMission({ ...verifiedMission(), ...patch })).toThrow()
  })
})

describe('recordings and preview', () => {
  it('keeps imported events without inventing missing evidence or an approval gate', () => {
    const m = parseRecording(JSON.stringify({ time: '2026-10-30T10:00:00Z', agent: 'verifier', event_type: 'TEST_FAILURE', tool: 'run_command', output_summary: 'Actual imported summary', output: 'Actual imported output' }))
    expect(m.events[0].summary).toBe('Actual imported summary')
    expect(m.events[0].output).toBe('Actual imported output')
    expect(m.criteria).toEqual([]); expect(m.tests).toEqual([]); expect(m.changes).toEqual([])
    expect(canApprove(m)).toBe(false)
  })
  it('reports malformed JSONL and refuses empty recordings', () => {
    expect(() => parseRecording('{}\ninvalid')).toThrow('Line 2')
    expect(() => parseRecording('')).toThrow('no events')
  })
  it('makes preview steps idempotent and leaves live missions untouched', () => {
    const first = previewStep(createPreview(), 0)
    expect(previewStep(first, 0)).toBe(first)
    const live = verifiedMission(); expect(previewStep(live, 0)).toBe(live)
  })
  it('finishes an explicitly illustrative journey without enabling repository application', () => {
    const m = PREVIEW_STORY.reduce((state, _, index) => previewStep(state, index), createPreview())
    expect(m.phase).toBe('awaiting_human'); expect(m.events).toHaveLength(PREVIEW_STORY.length)
    expect(m.issues[0].status).toBe('resolved'); expect(canApprove(m)).toBe(false)
    expect(m.tests[0].output).toContain('not executed tests')
  })
})
