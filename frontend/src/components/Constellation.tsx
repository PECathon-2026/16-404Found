import { motion } from 'motion/react'
import { ArrowUpRight, Crown } from 'lucide-react'
import { AGENTS, WORKERS, type AgentId } from '../lib/types'
import { AgentScene } from './AgentScene'
import { AgentIcon } from './AgentIcon'

export function Constellation({ active, onFocus }: { active: AgentId; onFocus: (id: AgentId) => void }) {
  return <div className="constellation">
    <div className="map-label"><span className="signal-dot" /> ORCHESTRATION MAP <span className="map-coordinate">SYS / 00—04</span></div>
    <div className="map-grid" />
    <svg className="network-paths" viewBox="0 0 800 540" preserveAspectRatio="none" aria-hidden="true">
      {['M400 248 C290 248 240 156 150 156','M400 248 C510 248 560 156 650 156','M400 248 C290 248 240 386 150 386','M400 248 C510 248 560 386 650 386'].map((d,i) => <g key={d}><path d={d} className="network-base" /><path d={d} className={`network-flow ${active===WORKERS[i]?'active':''}`} style={{stroke:AGENTS[WORKERS[i]].color}} /></g>)}
    </svg>
    <AgentScene />
    <button className="master-node" onClick={() => onFocus('master')} aria-label="Focus on Master orchestration"><Crown size={18} strokeWidth={1.6}/><span>MASTER</span><small>One system. In sync.</small></button>
    {WORKERS.map((id, i) => <motion.button key={id} className={`orbit-node orbit-${i} ${active===id?'is-active':''}`} style={{'--agent':AGENTS[id].color} as React.CSSProperties} onClick={() => onFocus(id)} whileHover={{y:-4}}>
      <span className="orbit-icon"><AgentIcon agent={id} size={18} strokeWidth={1.4}/></span>
      <span className="orbit-copy"><strong>{AGENTS[id].label}</strong><small>{AGENTS[id].role}</small></span><ArrowUpRight className="orbit-arrow" size={13}/>
    </motion.button>)}
    <div className="map-footer"><span>SHARED STATE</span><span className="map-footer-line"/><span>HUMAN IN CONTROL</span></div>
  </div>
}
