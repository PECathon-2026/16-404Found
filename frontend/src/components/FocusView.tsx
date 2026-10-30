import { useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { ArrowLeft, ArrowRight, ArrowUpRight, Maximize2, Pause, Play, X, Circle } from 'lucide-react'
import { AGENTS, WORKERS, type AgentId, type Mission } from '../lib/types'
import { AgentIcon } from './AgentIcon'
import { AgentScene } from './AgentScene'
import { Activity } from './Activity'
import { Criteria, Diff, Tests, Security } from './Evidence'

export function FocusView({ agent, mission, returnFocus, onClose, onFocus, playing, onPlay, autoFocus, onAutoFocus }: { agent: AgentId; mission: Mission; returnFocus:HTMLElement|null; onClose:()=>void; onFocus:(id:AgentId)=>void; playing:boolean; onPlay:()=>void; autoFocus:boolean; onAutoFocus:()=>void }) {
  const identity=AGENTS[agent]
  const root=useRef<HTMLElement>(null)
  const reduced=useReducedMotion()
  const [panel,setPanel]=useState<'evidence'|'activity'>('evidence')
  useEffect(()=>{setPanel('evidence')},[agent])
  useEffect(()=>{
    const previous=returnFocus
    const overflow=document.body.style.overflow
    document.body.style.overflow='hidden'
    root.current?.focus({preventScroll:true})
    const handler=(e:KeyboardEvent)=>{
      if(document.querySelector('dialog[open]'))return
      if(e.key==='Escape')onClose()
      if(e.key==='Tab'){
        const controls=Array.from(root.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input,summary,a[href]')??[]).filter(el=>el.getClientRects().length>0)
        const first=controls[0],last=controls.at(-1)
        if(e.shiftKey&&(document.activeElement===first||document.activeElement===root.current)){e.preventDefault();last?.focus()}
        else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}
      }
    }
    window.addEventListener('keydown',handler)
    return()=>{document.body.style.overflow=overflow;window.removeEventListener('keydown',handler);previous?.focus({preventScroll:true})}
  },[onClose,returnFocus])
  const sequence:AgentId[]=['master',...WORKERS]
  const next=sequence[(sequence.indexOf(agent)+1)%sequence.length]
  const active=mission.activeAgent===agent
  return <motion.section ref={root} tabIndex={-1} role="dialog" aria-modal="true" className="focus-view" style={{'--agent':identity.color} as React.CSSProperties} initial={{opacity:0,clipPath:reduced?undefined:'inset(0 0 100% 0)'}} animate={{opacity:1,clipPath:reduced?undefined:'inset(0 0 0% 0)'}} exit={{opacity:0,clipPath:reduced?undefined:'inset(100% 0 0 0)'}} transition={{duration:reduced?0:.55,ease:[.22,1,.36,1]}} aria-label={`${identity.label} focus mode`}>
    {!reduced&&<motion.div key={`${agent}-handoff`} className="handoff-wipe" aria-hidden="true" initial={{opacity:1,scaleY:1}} animate={{opacity:0,scaleY:0}} transition={{duration:.85,ease:[.76,0,.24,1]}}><span>{identity.role}</span><small>CONTROL TRANSFER / {identity.number}</small></motion.div>}
    <div className="focus-chrome"><button className="back-button" onClick={onClose}><ArrowLeft size={15}/>Mission control</button><div className="focus-center"><span className="signal-dot"/>{mission.source==='preview'?'DESIGN PREVIEW':mission.source==='recording'?'RECORDED MISSION':'LIVE MISSION'}<span className="chrome-slash">/</span>AGENT FOCUS</div><div className="focus-controls"><button className="icon-button" aria-label="Enter browser fullscreen" onClick={()=>{document.documentElement.requestFullscreen?.().catch(()=>{})}}><Maximize2 size={16}/></button><button className="icon-button" onClick={onClose} aria-label="Close agent focus"><X size={18}/></button></div></div>
    <div className="focus-body">
      <div className="focus-narrative"><motion.div key={`${agent}-copy`} initial={{opacity:0,y:30}} animate={{opacity:1,y:0}} transition={{duration:.6,delay:.1}}>
        <div className="focus-kicker"><span className="agent-number">{identity.number}</span><AgentIcon agent={agent} size={17}/><span>{identity.label.toUpperCase()} / {identity.role.toUpperCase()}</span></div>
        <h1>{identity.title}<br/><em>{identity.subtitle}</em></h1>
        <p className="focus-description">{agent==='master'?'A shared vision. Independent minds. The Master connects the evidence and decides the next move.':agent==='planner'?'The Architect explores your codebase, finds the constraints, and turns your request into a plan the whole team can trust.':agent==='developer'?'The Engineer works inside the workspace, follows your conventions, and changes direction when new evidence arrives.':agent==='verifier'?'The Verifier challenges the implementation with independent checks. Passing tests are the beginning, not the conclusion.':'The Sentinel follows the dependencies, questions the assumptions, and inspects the change before it reaches your repository.'}</p>
        <div className="focus-live"><span className={`live-pip ${active?'active':''}`}/><div><strong>{active?'Currently in focus':'Available to inspect'}</strong><span>{active?(mission.events.at(-1)?.summary??identity.action):identity.action}</span></div></div>
      </motion.div>
      <div className="focus-evidence"><div className="focus-panel-tabs"><button onClick={()=>setPanel('evidence')} aria-pressed={panel==='evidence'}>{agent==='planner'?'The blueprint':agent==='developer'?'The implementation':agent==='verifier'?'The evidence':agent==='reviewer'?'The review':'The mission'}</button><button onClick={()=>setPanel('activity')} aria-pressed={panel==='activity'}>Activity<ArrowUpRight size={12}/></button><span>{mission.source==='preview'?'ILLUSTRATIVE':'EVIDENCE'}</span></div><div className="focus-panel-content">{panel==='activity'?<Activity mission={mission} compact/>:agent==='planner'?<Criteria mission={mission}/>:agent==='developer'?<Diff mission={mission}/>:agent==='verifier'?<Tests mission={mission}/>:agent==='reviewer'?<Security mission={mission}/>:<div className="master-criteria"><p className="master-request">“{mission.request}”</p><Criteria mission={mission}/></div>}</div></div>
      </div>
      <div className={`focus-art focus-art-${agent}`}><motion.div key={`${agent}-scene`} className="focus-scene-wrap" initial={{opacity:0,scale:.8,rotate:-10}} animate={{opacity:1,scale:1,rotate:0}} transition={{duration:1,ease:[.22,1,.36,1]}}><AgentScene agent={agent}/></motion.div><div className="art-cross cross-top"/><div className="art-cross cross-bottom"/><div className="art-label">{identity.role.toUpperCase()} ENGINE<span>DEV / {identity.number}.SYSTEM</span></div><div className="art-status"><span className="signal-dot"/> {active?'IN THE LOOP':'STANDING BY'}</div><span className="art-caption">{agent==='planner'?'Structure before syntax.':agent==='developer'?'The shape of a good idea.':agent==='verifier'?'Proof, in every dimension.':agent==='reviewer'?'Built to hold the line.':'A little order in the chaos.'}</span></div>
    </div>
    <div className="focus-bottom"><div className="focus-agent-switcher">{sequence.map(id=><button key={id} onClick={()=>onFocus(id)} style={{'--agent':AGENTS[id].color} as React.CSSProperties} aria-pressed={id===agent} aria-label={`Focus ${AGENTS[id].label}`}><AgentIcon agent={id} size={15}/><span>{AGENTS[id].label}</span>{id===mission.activeAgent?<span className="switcher-dot"/>:<Circle size={7}/>}</button>)}</div><div className="focus-playback">{mission.source!=='recording'&&<button className="follow-toggle" onClick={onAutoFocus} aria-pressed={autoFocus}>Follow handoffs<span className={`toggle-track ${autoFocus?'on':''}`}><span/></span></button>}{mission.source==='preview'&&<button className="icon-button" onClick={onPlay} aria-label={playing?'Pause preview':'Play preview'}>{playing?<Pause size={17}/>:<Play size={17}/>}</button>}<button className="next-agent" onClick={()=>onFocus(next)}><span>Explore {AGENTS[next].label}</span><ArrowRight size={17}/></button></div></div>
  </motion.section>
}
