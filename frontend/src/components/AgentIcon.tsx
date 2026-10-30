import { Crown, Braces, Layers3, ScanLine, ShieldCheck, type LucideProps } from 'lucide-react'
import type { AgentId } from '../lib/types'

const icons = { master: Crown, planner: Layers3, developer: Braces, verifier: ScanLine, reviewer: ShieldCheck }
export function AgentIcon({ agent, ...props }: LucideProps & { agent: AgentId }) {
  const Icon = icons[agent]
  return <Icon {...props} />
}
