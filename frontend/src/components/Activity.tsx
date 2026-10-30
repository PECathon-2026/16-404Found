import { motion, AnimatePresence } from 'motion/react'
import { ArrowUpRight, ChevronDown, Radio } from 'lucide-react'
import { AGENTS, type Mission } from '../lib/types'
import { AgentIcon } from './AgentIcon'
import { useEffect, useState } from 'react'

export function Activity({ mission, compact = false }: { mission: Mission; compact?: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [limit, setLimit] = useState(8)
  useEffect(() => { setLimit(8); setExpanded(null) }, [mission.id])
  const events = [...mission.events].reverse().slice(0, compact ? 3 : limit)
  return <section className={`activity ${compact?'compact':''}`} aria-label="Mission activity">
    <div className="section-label"><span><Radio size={13}/> {mission.source==='preview'?'PREVIEW ACTIVITY':'MISSION ACTIVITY'}</span><span>{String(mission.events.length).padStart(2,'0')} EVENTS</span></div>
    <div className="activity-list" aria-live="polite" aria-relevant="additions">
      <AnimatePresence initial={false}>
        {events.map((event,i) => <motion.div key={event.id} className={`activity-event ${i===0?'latest':''}`} initial={{opacity:0,y:-10}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.3}}>
          <span className="event-icon" style={{color:AGENTS[event.agent].color}}><AgentIcon agent={event.agent} size={16}/></span>
          <div className="event-content"><div className="event-meta"><strong>{AGENTS[event.agent].label}</strong><span>{event.type.replaceAll('_',' ').toLowerCase()}</span><small>{event.time && !Number.isNaN(Date.parse(event.time)) ? new Date(event.time).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '—'}</small></div><p>{event.summary}</p>
            {event.output && <><button className="inline-action" onClick={()=>setExpanded(expanded===event.id?null:event.id)} aria-expanded={expanded===event.id}>Inspect output <ChevronDown size={12}/></button>{expanded===event.id && <pre className="event-output">{event.output}</pre>}</>}
          </div>{event.tool && <span className="event-tool">{event.tool}<ArrowUpRight size={10}/></span>}
        </motion.div>)}
      </AnimatePresence>
      {!events.length && <div className="activity-empty"><span className="empty-orbit"/><p>{mission.source==='preview'?'A little intent. A whole lot of possibility.':'Waiting for mission events.'}<small>{mission.source==='preview'?'Play the preview to see the team coordinate.':'Events will appear when the backend produces evidence.'}</small></p></div>}
    </div>
    {!compact && mission.events.length > limit && <button className="inline-action earlier-events" onClick={() => setLimit(previous => previous + 20)}>Show earlier activity <ChevronDown size={12}/></button>}
  </section>
}
