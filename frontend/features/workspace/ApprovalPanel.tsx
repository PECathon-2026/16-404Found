"use client";
import { CheckCircle2, GitPullRequest, MessageCircleQuestion, ShieldAlert, ThumbsDown, Undo2 } from "lucide-react";
import React, { useState } from "react";
import { Badge, Button, Card, CardHeader, ErrorCard, Modal, Mono, textareaCls, inputCls, Field, Github } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { shortSha } from "@/lib/format";
import type { Diffs, Finding, HumanRequest, MissionDetail, TestRun, Verification } from "@/lib/types";
import { CRIT_TONE } from "../missions/status";
import { VerificationSummary } from "./panels";

export function HumanRequestCard({ missionId, req, onDone }: { missionId: string; req: HumanRequest; onDone: () => void }) {
  const [opt, setOpt] = useState<string>(req.options[0]?.id ?? "answer");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const cur = req.options.find((o) => o.id === opt);
  const needsText = cur?.needs_text || (req.kind === "CLARIFICATION" && opt === "answer");
  async function send() {
    setBusy(true); setErr(null);
    try { await api.missions.respond(missionId, { request_id: req.id, option: opt, text: text.trim() || undefined }); onDone(); } catch (e) { setErr((e as ApiError).message); } finally { setBusy(false); }
  }
  return (
    <Card className="border-warning/40" role="region" aria-label="Question from DevPilot">
      <CardHeader title={<span className="flex items-center gap-2"><MessageCircleQuestion className="h-4 w-4 text-warning" aria-hidden />{req.kind === "CLARIFICATION" ? "DevPilot needs a decision" : "DevPilot stopped and needs you"}</span>} />
      <div className="space-y-3 p-4">
        <p className="whitespace-pre-wrap text-sm">{req.question}</p>
        {req.evidence_refs.length > 0 && <p className="text-xs text-fg3">Evidence: {req.evidence_refs.slice(0, 4).map((r, i) => <Badge key={i} className="mr-1">{r.kind} {r.id.slice(-6)}</Badge>)}</p>}
        <fieldset className="space-y-1.5"><legend className="sr-only">Options</legend>
          {req.options.map((o) => (<label key={o.id} className="flex cursor-pointer items-center gap-2 text-sm"><input type="radio" name={`opt-${req.id}`} checked={opt === o.id} onChange={() => setOpt(o.id)} />{o.label}</label>))}</fieldset>
        {(needsText || opt === "hint") && <textarea className={textareaCls} rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder={req.kind === "CLARIFICATION" ? "Your answer…" : "Guidance for the developer agent…"} aria-label="Your answer" />}
        {err && <p role="alert" className="text-sm text-danger">{err}</p>}
        <Button variant="primary" onClick={send} loading={busy} disabled={needsText && !text.trim()}>Send</Button>
      </div>
    </Card>
  );
}

export function ApprovalPanel({ d, diffs, tests, findings, verification, onDone }: {
  d: MissionDetail; diffs: Diffs | null; tests: TestRun[]; findings: Finding[]; verification: Verification | null; onDone: () => void;
}) {
  const gate = d.gate;
  const [ack, setAck] = useState<string[]>([]);
  const [push, setPush] = useState(false);
  const [pr, setPr] = useState(false);
  const [token, setToken] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [changes, setChanges] = useState(false);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const sha = d.current_patch_sha256;
  const github = d.repository?.source_type === "GIT_URL";
  const base = tests.find((t) => t.kind === "BASELINE");
  const fin = [...tests].reverse().find((t) => t.kind === "TEST" && t.patch_sha256 === sha);
  const open = findings.filter((f) => ["OPEN", "DISPUTED", "FIX_PROPOSED"].includes(f.status));
  const needAck = gate?.needs_ack ?? [];
  const ackOk = needAck.every((a) => ack.includes(a));
  const canApprove = !!gate?.clear && ackOk && !!sha;

  async function decide(decision: "APPROVED" | "REJECTED" | "CHANGES_REQUESTED") {
    if (!sha) return;
    setBusy(decision); setErr(null);
    try {
      await api.missions.approve(d.id, { decision, patch_sha256: sha, comment: comment.trim() || undefined, acknowledged_criteria: ack,
        publish: decision === "APPROVED" && github ? { push, open_pr: pr && push, github_token: token || undefined } : undefined });
      setToken(""); setConfirm(false); setChanges(false); onDone();
    } catch (e) { setErr(e as ApiError); setConfirm(false); } finally { setBusy(null); }
  }

  return (
    <Card className="border-approval/50" role="region" aria-label="Approval">
      <CardHeader title={<span className="flex items-center gap-2"><GitPullRequest className="h-4 w-4 text-approval" aria-hidden />Review and decide</span>} sub={<>patch <Mono>{shortSha(sha)}</Mono></>}
        right={<Badge tone={gate?.clear ? "success" : "danger"}>{gate?.clear ? "gate clear" : "gate blocked"}</Badge>} />
      <div className="space-y-4 p-4 text-sm">
        {gate && !gate.clear && <ul className="list-disc space-y-0.5 pl-5 text-danger">{gate.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
        {gate?.notes.map((n) => <p key={n} className="text-xs text-warning">{n}</p>)}
        <section aria-label="Criteria"><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg3">Acceptance criteria (independent verifier)</h4>
          <ul className="space-y-1">{d.acceptance_criteria.map((c) => (
            <li key={c.id} className="flex items-start gap-2"><Badge tone={CRIT_TONE[c.status]}>{c.status}</Badge><span className="min-w-0 flex-1 text-xs"><Mono>{c.id}</Mono> {c.text}
              {c.status === "INCONCLUSIVE" && <span className="block text-warning">Not machine-verifiable: you must acknowledge it.</span>}</span>
              {needAck.includes(c.id) && <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={ack.includes(c.id)} onChange={(e) => setAck(e.target.checked ? [...ack, c.id] : ack.filter((x) => x !== c.id))} />I checked this</label>}</li>))}</ul>
          <div className="mt-2"><VerificationSummary v={verification} /></div></section>
        <section aria-label="Tests"><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg3">Tests (system-captured)</h4>
          <p className="text-xs text-fg2">baseline: {base ? `${base.outcome} (${base.passed}/${base.total})` : "—"} → final: {fin ? <b>{fin.outcome} ({fin.passed}/{fin.total})</b> : "—"}</p></section>
        <section aria-label="Findings"><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg3">Security & quality</h4>
          <p className="text-xs text-fg2">{open.length === 0 ? "No open findings." : `${open.length} open: ${open.map((f) => `${f.severity} ${f.category}`).join(", ")}`} · {findings.filter((f) => f.status === "RESOLVED").length} resolved by re-scan</p></section>
        <section aria-label="Change"><h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-fg3">Change</h4>
          <ul className="text-xs">{(diffs?.files ?? []).map((f) => <li key={f.path}><Mono>{f.path}</Mono> <span className="text-success">+{f.additions}</span> <span className="text-danger">−{f.deletions}</span>{f.is_test_file && <Badge className="ml-1">test</Badge>}{f.tamper_flags.length > 0 && <Badge tone="danger" className="ml-1">tamper</Badge>}</li>)}</ul></section>
        {github && (
          <section aria-label="Publish to GitHub" className="space-y-2 rounded-md border border-line p-3">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg3"><Github className="h-3.5 w-3.5" aria-hidden />GitHub (optional, outward-facing)</h4>
            <p className="text-xs text-fg3">Approving always creates a <b>new branch</b> with the change in DevPilot’s clone of {d.repository?.github_owner}/{d.repository?.github_name}. Nothing leaves your machine unless you tick below.</p>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={push} onChange={(e) => { setPush(e.target.checked); if (!e.target.checked) setPr(false); }} />Push the branch to GitHub</label>
            <label className={`flex items-center gap-2 text-sm ${push ? "" : "opacity-50"}`}><input type="checkbox" disabled={!push} checked={pr} onChange={(e) => setPr(e.target.checked)} />Open a pull request</label>
            {push && <Field label="GitHub token with write access" hint="Used for this push only; not stored. Leave empty to use the backend's GITHUB_TOKEN."><input className={inputCls} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} /></Field>}
          </section>)}
        {err && <ErrorCard title={err.code === "STALE_PATCH" ? "The patch changed. Review it again." : "Could not record the decision"} message={err.message + (err.details?.reasons ? ": " + (err.details.reasons as string[]).join("; ") : "")} />}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => setConfirm(true)} disabled={!canApprove} loading={busy === "APPROVED"}><CheckCircle2 className="h-4 w-4" aria-hidden />Approve</Button>
          <Button onClick={() => setChanges(true)} loading={busy === "CHANGES_REQUESTED"}><Undo2 className="h-4 w-4" aria-hidden />Request changes</Button>
          <Button variant="danger" onClick={() => decide("REJECTED")} loading={busy === "REJECTED"}><ThumbsDown className="h-4 w-4" aria-hidden />Reject</Button>
        </div>
        {!canApprove && gate?.clear && !ackOk && <p className="text-xs text-warning">Tick “I checked this” for each manually-verified criterion to approve.</p>}
      </div>

      <Modal open={confirm} onClose={() => setConfirm(false)} title="Confirm approval">
        <div className="space-y-3 text-sm">
          <p>You are approving patch <Mono>{shortSha(sha)}</Mono>. This will:</p>
          <ul className="list-disc space-y-1 pl-5">
            {github ? <>
              <li>create branch <Mono>devpilot/…</Mono> with one commit in DevPilot’s clone of <b>{d.repository?.github_owner}/{d.repository?.github_name}</b></li>
              {push ? <li className="text-warning"><b>push that branch to GitHub</b>{pr && <> and <b>open a pull request</b></>}</li> : <li>not contact GitHub</li>}
            </> : <li>apply the patch to <Mono>{d.repository?.source_ref}</Mono> (you can roll it back from the report)</li>}
          </ul>
          <div className="flex justify-end gap-2"><Button variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button><Button variant="primary" onClick={() => decide("APPROVED")} loading={busy === "APPROVED"}>Approve and apply</Button></div>
        </div>
      </Modal>
      <Modal open={changes} onClose={() => setChanges(false)} title="Request changes">
        <p className="mb-2 text-sm text-fg2">Describe what should change. The developer agent gets this as repair guidance and everything is re-tested and re-verified.</p>
        <textarea className={textareaCls} rows={4} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="e.g. also handle empty input and add a test for it" />
        <div className="mt-3 flex justify-end gap-2"><Button variant="ghost" onClick={() => setChanges(false)}>Cancel</Button><Button variant="primary" onClick={() => decide("CHANGES_REQUESTED")} disabled={!comment.trim()} loading={busy === "CHANGES_REQUESTED"}>Send</Button></div>
      </Modal>
      <ShieldAlert className="hidden" />
    </Card>
  );
}
