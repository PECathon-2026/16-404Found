import { Check, Circle, TriangleAlert, FileCode2, LockKeyhole, ArrowUpRight, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import type { Mission } from '../lib/types'

export function Criteria({ mission }: { mission: Mission }) {
  return <div className="criteria-list">{mission.criteria.map(c => <div className={`criterion criterion-${c.status}`} key={c.id}><span className="criterion-icon">{c.status==='passed'?<Check size={13}/>:c.status==='failed'?<TriangleAlert size={13}/>:<Circle size={10}/>}</span><span><small>{c.id}</small><p>{c.text}</p>{c.evidence && <details><summary>Evidence</summary><pre>{c.evidence}</pre></details>}</span></div>)}{!mission.criteria.length&&<p className="muted-copy">No acceptance criteria in this recording.</p>}</div>
}

export function Diff({ mission }: { mission: Mission }) {
  const [mode,setMode]=useState<'split'|'unified'>('split')
  if(!mission.changes.length) return <div className="evidence-empty"><FileCode2 size={30} strokeWidth={1}/><h3>The change starts here.</h3><p>{mission.source==='preview'?'The Engineer’s proposed patch appears as the preview unfolds.':'No patch evidence has been provided for this mission.'}</p></div>
  return <div className="diff-view"><div className="diff-toolbar"><span><FileCode2 size={14}/>{mission.changes.length===1?mission.changes[0].path:`${mission.changes.length} changed files`}</span><div className="segmented"><button onClick={()=>setMode('split')} aria-pressed={mode==='split'}>Split</button><button onClick={()=>setMode('unified')} aria-pressed={mode==='unified'}>Unified</button></div></div>
    {mission.changes.map(change=><div className={`diff-file ${mode}`} key={change.path}>{mission.changes.length>1&&<div className="diff-file-path">{change.path}</div>}<div className="diff-before"><span className="diff-side-label">ORIGINAL</span>{change.before.split('\n').map((line,i)=><div className="code-line removed" key={i}><span>{i+1}</span><code>{mode==='unified'?'− ':''}{line}</code></div>)}</div><div className="diff-after"><span className="diff-side-label">PROPOSED</span>{change.after.split('\n').map((line,i)=><div className="code-line added" key={i}><span>{i+1}</span><code>{mode==='unified'?'+ ':''}{line}</code></div>)}</div></div>)}
    <div className="diff-footnote"><LockKeyhole size={12}/>{mission.source==='preview'?'Illustrative patch · no repository files are changed.':'Candidate change · applies only after verified human approval.'}</div>
  </div>
}

export function Tests({ mission }: { mission: Mission }) {
  return <div className="test-evidence">{mission.tests.map((t,i)=><section className="test-record" key={`${t.command}-${i}`}><div className="test-record-head"><span><span className={`test-dot ${t.status}`}/>{t.command}</span><span className={`test-verdict ${t.status}`}>{t.status}</span></div><pre>{t.output}</pre></section>)}{!mission.tests.length&&<div className="evidence-empty"><Circle size={28} strokeWidth={1}/><h3>Every claim needs a check.</h3><p>Test evidence will appear here when verification begins.</p></div>}</div>
}

export function Security({ mission }: { mission: Mission }) {
  return <div className="security-evidence"><div className="security-heading"><ShieldCheck size={22} strokeWidth={1.3}/><div><h3>A second look. A higher standard.</h3><p>Secrets, unsafe operations, and code quality.</p></div></div>{mission.issues.map(issue=><div className={`finding finding-${issue.status}`} key={issue.id}><span>{issue.status==='resolved'?<Check size={16}/>:<TriangleAlert size={16}/>}</span><div><small>{issue.severity.toUpperCase()} · {issue.file??'REVIEW FINDING'}</small><p>{issue.text}</p></div><span className="finding-status">{issue.status}<ArrowUpRight size={12}/></span></div>)}{!mission.issues.length&&<p className="muted-copy">{mission.phase==='reviewing'?'No findings have been received yet.':'Security findings appear when the Sentinel reviews the change.'}</p>}</div>
}
