/** Shared frontend contract: backend evidence and presentation are kept distinct. */
export type AgentId = 'master' | 'planner' | 'developer' | 'verifier' | 'reviewer'
export type Phase = 'planning' | 'building' | 'verifying' | 'reviewing' | 'awaiting_human' | 'done' | 'stopped' | 'escalated'
export type Source = 'preview' | 'recording' | 'live'
export type EvidenceStatus = 'pending' | 'passed' | 'failed' | 'unavailable'

export interface Criterion { id: string; text: string; status: EvidenceStatus; evidence?: string }
export interface MissionEvent { id: string; time: string; agent: AgentId; type: string; summary: string; tool?: string; output?: string }
export interface FileChange { path: string; before: string; after: string }
export interface Mission {
  id: string
  request: string
  repository: string
  phase: Phase
  activeAgent: AgentId
  source: Source
  events: MissionEvent[]
  criteria: Criterion[]
  changes: FileChange[]
  tests: { command: string; output: string; status: EvidenceStatus }[]
  issues: { id: string; text: string; severity: 'low' | 'medium' | 'high' | 'critical'; status: 'open' | 'resolved'; file?: string }[]
  approvalEligible: boolean
  patchHash?: string
}

export const AGENTS: Record<AgentId, { label: string; role: string; action: string; color: string; number: string; title: string; subtitle: string }> = {
  master: { label: 'Master', role: 'Orchestration', action: 'Coordinates the next move', color: '#d6f57c', number: '00', title: 'One vision.', subtitle: 'Every moving part.' },
  planner: { label: 'Architect', role: 'Planning', action: 'Turns intent into a plan', color: '#9ebdff', number: '01', title: 'First, intent.', subtitle: 'Then, a blueprint.' },
  developer: { label: 'Engineer', role: 'Execution', action: 'Brings the plan to life', color: '#ffc58d', number: '02', title: 'Ideas become', subtitle: 'something real.' },
  verifier: { label: 'Verifier', role: 'Testing', action: 'Puts every claim to the test', color: '#c6abff', number: '03', title: 'Trust is good.', subtitle: 'Evidence is better.' },
  reviewer: { label: 'Sentinel', role: 'Security & review', action: 'Looks where others don’t', color: '#8de3cb', number: '04', title: 'Nothing slips', subtitle: 'through the cracks.' },
}

export const WORKERS: AgentId[] = ['planner', 'developer', 'verifier', 'reviewer']
export const PHASES: Phase[] = ['planning', 'building', 'verifying', 'reviewing', 'awaiting_human']
export function phaseAgent(phase: Phase): AgentId {
  return ({ planning: 'planner', building: 'developer', verifying: 'verifier', reviewing: 'reviewer' } as Partial<Record<Phase, AgentId>>)[phase] ?? 'master'
}
