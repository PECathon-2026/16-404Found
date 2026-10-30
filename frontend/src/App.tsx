import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, MotionConfig } from 'motion/react'
import { Asterisk, ArrowUpRight, ArrowRight, Plus, Play, Pause, RotateCcw, GitBranch, ChevronRight, Command, CircleHelp, Settings2, LayoutDashboard, History, Terminal, Maximize2, Upload, Check, LockKeyhole, Radio, X, Link2, FolderGit2, Eye, Activity as ActivityIcon, FileCode2, ShieldCheck, Layers3 } from 'lucide-react'
import { AGENTS, WORKERS, PHASES, type AgentId, type Mission } from './lib/types'
import { createPreview, PREVIEW_STORY, previewStep } from './preview/mission'
import { canApprove, createMission, decideMission, fetchMission, parseRecording } from './lib/transport'
import { AgentIcon } from './components/AgentIcon'
import { Constellation } from './components/Constellation'
import { Activity } from './components/Activity'
import { Criteria, Diff, Tests, Security } from './components/Evidence'
import { FocusView } from './components/FocusView'
import { Dialog } from './components/Dialog'

type Panel='activity'|'plan'|'changes'|'tests'|'security'
type Modal='mission'|'connect'|'history'|'help'|'approval'|null
const tabs: {id:Panel;label:string;icon:typeof ActivityIcon}[]=[{id:'activity',label:'Activity',icon:ActivityIcon},{id:'plan',label:'Plan',icon:Layers3},{id:'changes',label:'Changes',icon:FileCode2},{id:'tests',label:'Tests',icon:Terminal},{id:'security',label:'Security',icon:ShieldCheck}]

export default function App() {
  const [mission,setMission]=useState<Mission>(()=>createPreview())
  const [playing,setPlaying]=useState(false)
  const [step,setStep]=useState(-1)
  const [focus,setFocus]=useState<AgentId|null>(null)
  const [autoFocus,setAutoFocus]=useState(true)
  const [panel,setPanel]=useState<Panel>('activity')
  const [modal,setModal]=useState<Modal>(null)
  const [notice,setNotice]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [request,setRequest]=useState('Add coupon support. SAVE10 gives 10% off.')
  const [repository,setRepository]=useState('mini_shop')
  const [baseUrl,setBaseUrl]=useState('http://127.0.0.1:8000/api')
  const [missionId,setMissionId]=useState('')
  const [connectedBase,setConnectedBase]=useState('')
  const [history,setHistory]=useState<Mission[]>([])
  const [connection,setConnection]=useState<'connected'|'reconnecting'|'offline'>('offline')
  const fileInput=useRef<HTMLInputElement>(null)
  const polling=useRef(false)
  const returnFocus=useRef<HTMLElement|null>(null)
  const openFocus=(id:AgentId)=>{returnFocus.current=document.activeElement as HTMLElement;setFocus(id)}
  const closeFocus=useCallback(()=>setFocus(null),[])
  const setDialog=(value:Modal)=>{setError('');setModal(value)}

  useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(''),5000);return()=>clearTimeout(timer)},[notice])
  useEffect(()=>{
    if(!playing||mission.source!=='preview')return
    const timer=setTimeout(()=>setStep(previous=>Math.min(previous+1,PREVIEW_STORY.length-1)),step<0?200:3400)
    return()=>clearTimeout(timer)
  },[playing,step,mission.source])
  useEffect(()=>{
    if(step<0)return
    setMission(previous=>previewStep(previous,step))
    if(step===PREVIEW_STORY.length-1)setPlaying(false)
  },[step])
  useEffect(()=>{if(focus!==null&&autoFocus&&(playing||mission.source==='live'))setFocus(mission.activeAgent)},[mission.activeAgent,mission.source,autoFocus,playing,focus])
  useEffect(()=>{
    if(!connectedBase||mission.source!=='live'||busy)return
    const controller=new AbortController()
    const update=async()=>{
      if(polling.current)return
      polling.current=true
      try{const next=await fetchMission(connectedBase,mission.id,controller.signal);if(!controller.signal.aborted){setMission(next);setConnection('connected')}}
      catch{if(!controller.signal.aborted)setConnection('reconnecting')}
      finally{polling.current=false}
    }
    const timer=setInterval(update,2500)
    return()=>{controller.abort();clearInterval(timer)}
  },[connectedBase,mission.id,mission.source,busy])
  useEffect(()=>{
    const keydown=(event:KeyboardEvent)=>{
      if((event.metaKey||event.ctrlKey)&&event.key==='k'){event.preventDefault();setModal('mission')}
      if(event.key==='Escape'&&!document.querySelector('dialog[open]'))setFocus(null)
    }
    window.addEventListener('keydown',keydown);return()=>window.removeEventListener('keydown',keydown)
  },[])

  const resetPreview=()=>{setHistory(previous=>mission.events.length?[mission,...previous].slice(0,10):previous);setPlaying(false);setStep(-1);setMission(createPreview());setConnectedBase('');setConnection('offline');setFocus(null);setPanel('activity')}
  const togglePlayback=()=>{if(step>=PREVIEW_STORY.length-1){setStep(-1);setMission(createPreview(mission.request,mission.repository))}setPlaying(previous=>!previous)}
  const advance=()=>{setPlaying(false);if(step<PREVIEW_STORY.length-1)setStep(previous=>previous+1)}
  const importRecording=async(file:File)=>{
    if(file.size>10*1024*1024){setNotice('Choose a recording smaller than 10 MB.');return}
    try{const next=parseRecording(await file.text());setHistory(previous=>[mission,...previous].slice(0,10));setPlaying(false);setStep(-1);setFocus(null);setConnectedBase('');setMission(next);setModal(null);setNotice('Recording loaded. Only evidence present in the file is shown.')}
    catch(e){setNotice(e instanceof Error?e.message:'Unable to read this recording.')}
  }
  const connect=async()=>{
    if(!missionId.trim()){setError('Enter a mission ID to connect.');return}
    setBusy(true);setError('')
    try{const next=await fetchMission(baseUrl,missionId.trim(),AbortSignal.timeout(10000));setPlaying(false);setFocus(null);setStep(-1);setMission(next);setConnectedBase(baseUrl);setConnection('connected');setModal(null);setNotice('Connected. Mission evidence now comes from your backend.')}
    catch(e){setError(e instanceof Error?e.message:'Could not connect to the backend.')}
    finally{setBusy(false)}
  }
  const launch=async()=>{
    if(!request.trim()){setError('Describe the change you want to make.');return}
    if(!connectedBase){resetPreview();setModal(null);setPlaying(true);setNotice('Playing the illustrative coupon workflow. No real mission was started.');return}
    setBusy(true);setError('')
    try{const next=await createMission(connectedBase,request.trim(),repository,AbortSignal.timeout(15000));setMission(next);setModal(null);setNotice('Mission submitted to your backend.')}
    catch(e){setError(e instanceof Error?e.message:'Mission could not be created.')}
    finally{setBusy(false)}
  }
  const decide=async(decision:'approve'|'reject')=>{
    if(mission.source!=='live'){setNotice('Preview inspected. No repository was modified.');setModal(null);return}
    setBusy(true);setError('')
    try{const next=await decideMission(connectedBase,mission,decision,AbortSignal.timeout(15000));setMission(next);setModal(null);setNotice(decision==='approve'?'Approval submitted. The backend controls application.':'Mission rejected.')}
    catch(e){setError(e instanceof Error?e.message:'Decision could not be submitted.')}
    finally{setBusy(false)}
  }
  const currentPhase=mission.phase==='done'?PHASES.length:PHASES.indexOf(mission.phase)
  const isPreview=mission.source==='preview'
  const phases=['Plan','Build','Verify','Review','Your move']
  const finished=mission.phase==='awaiting_human'||mission.phase==='done'
  return <MotionConfig reducedMotion="user"><div className="app-shell">
    <aside className="rail" inert={focus!==null}><button className="brand-mark" onClick={()=>{setFocus(null);setPanel('activity')}} aria-label="DevPilot mission control"><Asterisk size={29} strokeWidth={1.8}/></button><div className="rail-nav"><button className={`rail-button ${modal===null?'selected':''}`} onClick={()=>{setFocus(null);setModal(null)}} aria-label="Mission overview"><LayoutDashboard size={19} strokeWidth={1.6}/></button><button className="rail-button" onClick={()=>setDialog('history')} aria-label="Mission history"><History size={19} strokeWidth={1.6}/></button><button className="rail-button" onClick={()=>fileInput.current?.click()} aria-label="Import a recorded run"><FolderGit2 size={19} strokeWidth={1.6}/></button></div><div className="rail-bottom"><button className="rail-button" onClick={()=>setDialog('help')} aria-label="Help and shortcuts"><CircleHelp size={19} strokeWidth={1.6}/></button><button className="rail-button" onClick={()=>setDialog('connect')} aria-label="Backend connection settings"><Settings2 size={19} strokeWidth={1.6}/></button><span className="team-avatar">404</span></div></aside>
    <div className="workspace" inert={focus!==null}><header className="topbar"><div className="wordmark">devpilot<span className="wordmark-dot">✳</span></div><span className="topbar-divider"/><div className="breadcrumb">Workspace<ChevronRight size={12}/><strong>Mission control</strong></div><div className="topbar-right"><button className={`source-badge source-${mission.source}`} onClick={()=>setDialog('connect')}><span className={`signal-dot ${mission.source==='live'&&connection!=='connected'?'warning':''}`}/>{isPreview?'DESIGN PREVIEW':mission.source==='recording'?'RECORDED RUN':connection==='connected'?'LIVE BACKEND':'RECONNECTING'}<ArrowUpRight size={11}/></button><span className="team-label">404Found<small>PECATHON ’26</small></span></div></header>
      <main className="main-content"><div className="page-heading"><div><div className="eyebrow"><span className="tiny-cross"/> THE SPACE BETWEEN INTENT & IMPACT</div><h1>Mission control<span className="heading-period">.</span></h1></div><button className="primary-button new-mission" onClick={()=>setDialog('mission')}><Plus size={15}/>New mission<span className="button-shortcut"><Command size={10}/>K</span></button></div>
        <section className="mission-hero"><div className="mission-narrative"><div className="mission-kicker"><span className="mission-live-label"><span className="signal-dot"/>{finished?'READY FOR YOUR REVIEW':isPreview?'YOUR NEXT GREAT CHANGE':mission.source==='recording'?'RECORDED MISSION':mission.phase==='escalated'?'HUMAN INPUT NEEDED':mission.phase==='stopped'?'MISSION STOPPED':'MISSION IN PROGRESS'}</span><span className="mission-reference">{isPreview?'PREVIEW / 001':mission.id}</span></div><h2>{finished?<>The team’s done.<br/><em>Your move.</em></>:<>A little intent.<br/><em>A big leap forward.</em></>}</h2><p className="hero-description">Independent minds. One shared mission.<br/>From the first idea to the final human decision.</p><div className="mission-brief"><div className="repo-label"><GitBranch size={13}/>{mission.repository}<span className="repo-branch">workspace</span><span className="brief-badge">{isPreview?'PREVIEW':mission.source==='recording'?'RECORDING':'LIVE'}</span></div><p>{mission.request}</p><div className="brief-bottom"><div className="stacked-avatars">{WORKERS.map(id=><span key={id} style={{color:AGENTS[id].color}}><AgentIcon agent={id} size={12}/></span>)}</div><span>4 specialists. 1 orchestrator.</span><button aria-label="Inspect the mission plan" onClick={()=>setPanel('plan')}><ArrowUpRight size={16}/></button></div></div><div className="hero-actions">{isPreview?<><button className="primary-button" onClick={togglePlayback}>{playing?<Pause size={14}/>:<Play size={14} fill="currentColor"/>}{playing?'Pause preview':step>=PREVIEW_STORY.length-1?'Replay the journey':'Play the journey'}</button><button className="text-button" onClick={()=>{openFocus(mission.activeAgent);if(!playing&&!finished)setPlaying(true)}}><Maximize2 size={14}/>Enter focus mode<ArrowUpRight size={12}/></button></>:<><button className="primary-button" onClick={()=>openFocus(mission.activeAgent)}><Maximize2 size={14}/>Enter focus mode</button><button className="text-button" onClick={()=>setPanel('activity')}>Inspect evidence<ArrowUpRight size={12}/></button></>}</div></div><Constellation active={mission.activeAgent} onFocus={openFocus}/></section>
        <section className="journey-strip" aria-label="Mission phases"><div className="journey-label"><span className="tiny-cross"/>THE JOURNEY</div><div className="journey-stages">{phases.map((label,i)=><button key={label} className={`journey-stage ${i<currentPhase?'complete':i===currentPhase?'current':''}`} onClick={()=>i===4?setDialog('approval'):openFocus(WORKERS[i])}><span>{i<currentPhase?<Check size={11}/>:String(i+1).padStart(2,'0')}</span><strong>{label}</strong>{i===currentPhase&&<span className="journey-pulse"/>}{i<4&&<span className="journey-connector"/>}</button>)}</div>{isPreview?<div className="journey-controls"><button className="icon-button" onClick={resetPreview} aria-label="Reset preview"><RotateCcw size={13}/></button><button className="icon-button" onClick={advance} disabled={step>=PREVIEW_STORY.length-1} aria-label="Advance preview one event"><ArrowRight size={15}/></button></div>:<span className="journey-source">{mission.source==='recording'?'RECORDING':mission.phase==='escalated'?'ESCALATED':mission.phase==='stopped'?'STOPPED':'LIVE'}</span>}</section>
        <div className="team-heading"><div className="section-label"><span>THE MINDS BEHIND THE MISSION</span></div><button className="text-button subtle" onClick={()=>openFocus('master')}>Coordinated by Master<ArrowUpRight size={13}/></button></div>
        <section className="agent-deck" aria-label="Specialist agents">{WORKERS.map((id,i)=><motion.button key={id} className={`agent-card ${mission.activeAgent===id?'active':''}`} style={{'--agent':AGENTS[id].color} as React.CSSProperties} onClick={()=>openFocus(id)} whileHover={{y:-5}} transition={{duration:.2}}><div className="agent-card-top"><span className="agent-card-icon"><AgentIcon agent={id} size={21} strokeWidth={1.4}/></span><span className="agent-card-number">0{i+1}</span><ArrowUpRight className="card-arrow" size={16}/></div><h3>{AGENTS[id].label}</h3><p>{AGENTS[id].action}</p><div className="agent-card-bottom"><span>{AGENTS[id].role}</span><span className={`agent-status ${mission.activeAgent===id?'working':''}`}><span/>{mission.activeAgent===id?'In focus':'Standing by'}</span></div></motion.button>)}</section>
        <section className="evidence-section"><div className="evidence-tabs" role="tablist" aria-label="Mission evidence">{tabs.map(({id,label,icon:Icon})=><button key={id} id={`tab-${id}`} role="tab" aria-selected={panel===id} aria-controls="mission-evidence-panel" className={panel===id?'selected':''} onClick={()=>setPanel(id)}><Icon size={14}/>{label}{id==='changes'&&mission.changes.length>0&&<span className="tab-count">{mission.changes.length}</span>}</button>)}<span className="evidence-source"><LockKeyhole size={11}/>{isPreview?'Preview · no real execution':'Evidence from your mission'}</span></div><div className="evidence-panel" id="mission-evidence-panel" role="tabpanel" aria-labelledby={`tab-${panel}`}><AnimatePresence mode="wait" initial={false}><motion.div key={panel} initial={{opacity:0,y:5}} animate={{opacity:1,y:0}} exit={{opacity:0}} transition={{duration:.15}}>{panel==='activity'?<Activity mission={mission}/>:panel==='plan'?<div className="plan-panel"><div><span className="eyebrow">ACCEPTANCE CRITERIA</span><h3>A plan with a point.</h3><p>Each criterion needs independent evidence.</p></div><Criteria mission={mission}/></div>:panel==='changes'?<Diff mission={mission}/>:panel==='tests'?<Tests mission={mission}/>:<Security mission={mission}/>}</motion.div></AnimatePresence></div></section>
        <footer className="footer"><span><Asterisk size={12}/> BUILT BY 404FOUND</span><span>{isPreview?'Design preview. Illustrative states, never real test results.':'Human judgment stays at the center.'}</span><span>PECATHON 2026<span className="footer-dot"/>PS—001</span></footer>
      </main>
    </div>
    <input ref={fileInput} type="file" accept=".jsonl,.json,.txt" hidden onChange={event=>{const file=event.target.files?.[0];if(file)void importRecording(file);event.target.value=''}}/>
    <AnimatePresence>{focus!==null&&<FocusView key="focus" agent={focus} returnFocus={returnFocus.current} mission={mission} onClose={closeFocus} onFocus={id=>{setAutoFocus(false);setFocus(id)}} playing={playing} onPlay={togglePlayback} autoFocus={autoFocus} onAutoFocus={()=>setAutoFocus(previous=>!previous)}/>}</AnimatePresence>
    {modal==='mission'&&<Dialog title="Start with an idea." onClose={()=>setDialog(null)}><p className="dialog-description">Tell the team what you want to build. They’ll handle the next steps.</p><form onSubmit={e=>{e.preventDefault();void launch()}}><label className="form-label" htmlFor="repo">REPOSITORY</label><div className="input-wrap"><GitBranch size={15}/><input id="repo" value={repository} onChange={e=>setRepository(e.target.value)} required placeholder="Repository path or ID"/></div><label className="form-label" htmlFor="request">YOUR MISSION</label><textarea id="request" value={request} onChange={e=>setRequest(e.target.value)} rows={4} required/><div className="mission-permissions"><span><LockKeyhole size={13}/>Isolated workspace</span><span><Eye size={13}/>Human approval</span></div>{!connectedBase&&<p className="preview-note">The backend is not connected. This button plays the illustrative coupon workflow; it does not execute your request.</p>}{error&&<p role="alert" className="form-error">{error}</p>}<button className="primary-button full-width" disabled={busy}>{busy?'Starting…':connectedBase?'Launch mission':'Launch design preview'}<ArrowUpRight size={15}/></button></form></Dialog>}
    {modal==='connect'&&<Dialog title="Bring it to life." onClose={()=>setDialog(null)}><p className="dialog-description">Connect a live backend mission, or inspect a recording from a real run.</p><form onSubmit={e=>{e.preventDefault();void connect()}}><label className="form-label" htmlFor="backend">BACKEND API URL</label><div className="input-wrap"><Link2 size={15}/><input id="backend" type="url" value={baseUrl} onChange={e=>setBaseUrl(e.target.value)} required/></div><label className="form-label" htmlFor="mission-id">MISSION ID</label><input id="mission-id" className="plain-input" value={missionId} onChange={e=>setMissionId(e.target.value)} placeholder="run_…"/>{error&&<p className="form-error" role="alert">{error}</p>}<button className="primary-button full-width" disabled={busy}>{busy?'Connecting…':'Connect mission'}<ArrowUpRight size={15}/></button></form><button className="secondary-button full-width import-button" onClick={()=>fileInput.current?.click()}><Upload size={15}/>Import a JSONL recording</button><p className="preview-note">Until connected, every animated journey is explicitly labeled as a design preview.</p></Dialog>}
    {modal==='history'&&<Dialog title="Every mission has a story." onClose={()=>setDialog(null)}><p className="dialog-description">Missions inspected in this session. Import a run to revisit its actual evidence.</p><div className="history-list">{history.length?history.map((m,i)=><button key={`${m.id}-${i}`} onClick={()=>{setPlaying(false);setStep(m.source==='preview'?m.events.length-1:-1);setMission(m.source==='live'?{...m,source:'recording',approvalEligible:false}:m);setFocus(null);setConnectedBase('');setConnection('offline');setModal(null)}}><span className="history-icon"><History size={18}/></span><span><strong>{m.repository}</strong><small>{m.request}</small></span><span className="history-source">{m.source}</span><ArrowUpRight size={14}/></button>):<div className="history-empty"><History size={25} strokeWidth={1}/><p>Your next mission starts the story.</p></div>}</div><button className="secondary-button full-width" onClick={()=>fileInput.current?.click()}><Upload size={14}/>Import recorded mission</button></Dialog>}
    {modal==='help'&&<Dialog title="Your controls. Your call." onClose={()=>setDialog(null)}><div className="help-list"><p><span>Prepare a mission</span><kbd>⌘ / Ctrl K</kbd></p><p><span>Leave agent focus</span><kbd>Esc</kbd></p><p><span>Inspect an agent</span><span>Click its node or card</span></p><p><span>Walk through the preview</span><span>Arrow in the journey strip</span></p></div><p className="dialog-description">Focus mode follows agent handoffs while the preview plays. You can turn following off and explore any agent independently.</p><div className="help-note"><Radio size={17}/><p>Preview is a visual walkthrough. Recorded runs show imported events. Live mode shows backend evidence and requires a verified gate before approval.</p></div></Dialog>}
    {modal==='approval'&&<Dialog title="The last move is yours." onClose={()=>setDialog(null)}><p className="dialog-description">Inspect the change and its evidence before making the call.</p><div className="approval-summary"><div><span>Acceptance criteria</span><strong>{mission.criteria.filter(c=>c.status==='passed').length} / {mission.criteria.length}</strong></div><div><span>Open review findings</span><strong>{mission.issues.filter(i=>i.status==='open').length}</strong></div><div><span>Source</span><strong>{mission.source==='preview'?'Design preview':mission.source==='recording'?'Recorded run':'Live backend'}</strong></div></div><Diff mission={mission}/><details className="approval-evidence"><summary>Inspect verification & review evidence</summary><Criteria mission={mission}/><Tests mission={mission}/><Security mission={mission}/></details>{!canApprove(mission)&&<p className="preview-note">{isPreview?'This is an illustrative approval screen. No files will be applied.':mission.source==='recording'?'A recorded run cannot apply changes.':'Approval is unavailable until the backend gate is clear and all criteria have passing evidence.'}</p>}{error&&<p role="alert" className="form-error">{error}</p>}<div className="approval-actions"><button className="secondary-button" onClick={()=>isPreview?setDialog(null):void decide('reject')} disabled={busy||mission.source==='recording'}>{isPreview?'Back to mission':'Reject change'}</button><button className="primary-button" onClick={()=>void decide('approve')} disabled={busy||(!isPreview&&!canApprove(mission))}>{isPreview?'Finish preview':busy?'Submitting…':'Approve change'}<Check size={14}/></button></div></Dialog>}
    <AnimatePresence>{notice&&<motion.div className="toast" role="status" initial={{opacity:0,y:20}} animate={{opacity:1,y:0}} exit={{opacity:0,y:20}}><span className="signal-dot"/>{notice}<button aria-label="Dismiss notification" onClick={()=>setNotice('')}><X size={15}/></button></motion.div>}</AnimatePresence>
  </div></MotionConfig>
}
