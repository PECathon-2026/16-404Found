/** Backend boundary. Preview actions never call a real approval endpoint. */
import type { AgentId, Mission, MissionEvent, Phase } from './types'
import { phaseAgent } from './types'

const agents = new Set<AgentId>(['master', 'planner', 'developer', 'verifier', 'reviewer'])
const phases = new Set<Phase>(['planning', 'building', 'verifying', 'reviewing', 'awaiting_human', 'done', 'stopped', 'escalated'])

export function parseRecording(text: string): Mission {
  const rows: Record<string, unknown>[] = text.split('\n').filter(line => line.trim()).map((line, i) => {
    try { const row: unknown = JSON.parse(line); if (!row || typeof row !== 'object' || Array.isArray(row)) throw new Error(); return row as Record<string, unknown> }
    catch { throw new Error(`Line ${i + 1} is not a valid JSON event.`) }
  })
  if (!rows.length) throw new Error('This recording contains no events.')
  const events: MissionEvent[] = rows.map((row, i) => ({
    id: typeof row.id === 'string' ? row.id : `recorded-${i}`,
    time: typeof row.time === 'string' ? row.time : '',
    agent: agents.has(row.agent as AgentId) ? row.agent as AgentId : 'master',
    type: typeof row.event_type === 'string' ? row.event_type : 'EVENT',
    summary: typeof row.output_summary === 'string' && row.output_summary ? row.output_summary : typeof row.input === 'string' ? row.input : 'Recorded event',
    tool: typeof row.tool === 'string' ? row.tool : undefined,
    output: typeof row.output === 'string' ? row.output : undefined,
  }))
  const last = events.at(-1)!
  return {
    id: typeof rows[0].run_id === 'string' ? rows[0].run_id : 'imported-recording',
    repository: 'Imported run', request: typeof rows[0].request === 'string' ? rows[0].request : 'Recorded mission',
    phase: 'stopped', activeAgent: last.agent, source: 'recording', events,
    criteria: [], changes: [], tests: [], issues: [], approvalEligible: false,
  }
}

export function validateMission(value: unknown): Mission {
  if (!value || typeof value !== 'object') throw new Error('The backend returned an invalid mission.')
  const m = value as Partial<Mission>
  if (typeof m.id !== 'string' || typeof m.request !== 'string' || typeof m.repository !== 'string' || !phases.has(m.phase as Phase) || !Array.isArray(m.events) || !Array.isArray(m.criteria) || !Array.isArray(m.changes) || !Array.isArray(m.tests) || !Array.isArray(m.issues)) throw new Error('Mission response does not match the frontend contract.')
  if (m.patchHash !== undefined && (typeof m.patchHash !== 'string' || !m.patchHash.trim())) throw new Error('The backend returned an invalid patch identity.')
  for (const event of m.events) if (!event || typeof event.id !== 'string' || typeof event.time !== 'string' || typeof event.type !== 'string' || typeof event.summary !== 'string' || !agents.has(event.agent) || (event.output !== undefined && typeof event.output !== 'string') || (event.tool !== undefined && typeof event.tool !== 'string')) throw new Error('The backend returned an invalid event.')
  for (const c of m.criteria) if (!c || typeof c.id !== 'string' || typeof c.text !== 'string' || !['pending', 'passed', 'failed', 'unavailable'].includes(c.status) || (c.evidence !== undefined && typeof c.evidence !== 'string')) throw new Error('The backend returned an invalid criterion.')
  for (const c of m.changes) if (!c || typeof c.path !== 'string' || typeof c.before !== 'string' || typeof c.after !== 'string') throw new Error('The backend returned an invalid file change.')
  for (const t of m.tests) if (!t || typeof t.command !== 'string' || typeof t.output !== 'string' || !['pending', 'passed', 'failed', 'unavailable'].includes(t.status)) throw new Error('The backend returned an invalid test record.')
  for (const i of m.issues) if (!i || typeof i.id !== 'string' || typeof i.text !== 'string' || !['low', 'medium', 'high', 'critical'].includes(i.severity) || !['open', 'resolved'].includes(i.status) || (i.file !== undefined && typeof i.file !== 'string')) throw new Error('The backend returned an invalid review issue.')
  return { ...m, source: 'live', activeAgent: agents.has(m.activeAgent as AgentId) ? m.activeAgent! : phaseAgent(m.phase!), approvalEligible: m.approvalEligible === true } as Mission
}

export function canApprove(m: Mission): boolean {
  return m.source === 'live' && m.phase === 'awaiting_human' && m.approvalEligible && typeof m.patchHash === 'string' && !!m.patchHash.trim() && m.changes.length > 0 && m.criteria.length > 0 && m.criteria.every(c => c.status === 'passed' && !!c.evidence?.trim()) && m.tests.length > 0 && m.tests.every(t => t.status === 'passed' && !!t.output.trim()) && m.issues.every(i => i.status === 'resolved')
}

export async function fetchMission(base: string, id: string, signal?: AbortSignal): Promise<Mission> {
  const response = await fetch(`${base.replace(/\/$/, '')}/missions/${encodeURIComponent(id)}`, { signal })
  if (!response.ok) throw new Error(`Backend connection failed (${response.status}).`)
  return validateMission(await response.json())
}

export async function createMission(base: string, request: string, repository: string, signal?: AbortSignal): Promise<Mission> {
  const response = await fetch(`${base.replace(/\/$/, '')}/missions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request, repository }), signal,
  })
  if (!response.ok) throw new Error(`Mission could not be created (${response.status}).`)
  return validateMission(await response.json())
}

export async function decideMission(base: string, mission: Mission, decision: 'approve' | 'reject', signal?: AbortSignal): Promise<Mission> {
  if (mission.source !== 'live') throw new Error('Preview and recorded missions cannot modify a repository.')
  if (decision === 'approve' && !canApprove(mission)) throw new Error('The verified approval gate is not clear.')
  const response = await fetch(`${base.replace(/\/$/, '')}/missions/${encodeURIComponent(mission.id)}/approval`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision, patch_hash: mission.patchHash }), signal,
  })
  if (!response.ok) throw new Error(`Decision failed (${response.status}). Refresh the evidence and try again.`)
  return validateMission(await response.json())
}
