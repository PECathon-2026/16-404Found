"use client";
import { motion } from "framer-motion";
import { Ban, GitBranch, Pause, Play, ShieldCheck, Timer, UserCheck } from "lucide-react";
import Link from "next/link";
import React, { useState, useSyncExternalStore } from "react";
import { useToast } from "@/components/Toast";
import { Badge, Button, EmptyState, Github, Mono, Modal } from "@/components/ui";
import { api } from "@/lib/api";
import { shortId } from "@/lib/format";
import { TERMINAL, type Finding, type MissionDetail, type Task, type TestRun, type Verification, type Diffs } from "@/lib/types";
import { MissionStatusBadge } from "../missions/status";
import { ApprovalPanel, HumanRequestCard } from "../workspace/ApprovalPanel";
import { guild } from "./identity";

const sub = (cb: () => void) => { const t = setInterval(cb, 1000); return () => clearInterval(t); };
const useSeconds = () => useSyncExternalStore(sub, () => Math.floor(Date.now() / 1000), () => 0);
const hms = (s: number) => { const m = Math.floor(s / 60); return `${m}m ${String(s % 60).padStart(2, "0")}s`; };

export function ActiveMissionPanel({ d, tasks, tests, findings, verification, diffs, onChanged }: {
  d: MissionDetail | null; tasks: Task[]; tests: TestRun[]; findings: Finding[]; verification: Verification | null; diffs: Diffs | null; onChanged: () => void;
}) {
  const toast = useToast();
  const sec = useSeconds();
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  if (!d) return <EmptyState title="No mission yet" description="Start one and its live state appears here." action={<Link href="/missions/new"><Button variant="primary">New mission</Button></Link>} />;
  const done = tasks.filter((t) => t.status === "DONE").length, total = tasks.filter((t) => t.status !== "SUPERSEDED").length;
  const terminal = TERMINAL.includes(d.status);
  const end = terminal ? new Date(d.updated_at).getTime() : sec * 1000;
  const elapsed = Math.max(0, Math.round((end - new Date(d.created_at).getTime()) / 1000));
  const current = d.agents.find((a) => a.status === "thinking");
  const act = async (name: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(name);
    try { await fn(); toast("success", ok); onChanged(); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(null); }
  };
  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-start justify-between gap-2"><Link href={`/missions/${d.id}`} className="text-lg font-semibold leading-snug hover:text-cyan">{d.title}</Link><Mono className="mt-1 shrink-0 text-fg3">{shortId(d.id)}</Mono></div>
        <p className="mt-1 line-clamp-3 text-sm text-fg2">{d.request}</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <MissionStatusBadge status={d.status} reason={d.status_reason} />{d.mode === "scripted" && <Badge title="Scripted model replay; tools, tests, verifier and gate are real">demo model</Badge>}
        {d.status === "AWAITING_APPROVAL" && <Badge tone="approval">review &amp; approve</Badge>}
      </div>
      <div><div className="flex justify-between text-xs text-fg3"><span>{done} / {total || "—"} tasks</span><span className="inline-flex items-center gap-1"><Timer className="h-3 w-3" aria-hidden />{hms(elapsed)}</span></div>
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-hover" role="progressbar" aria-label="Mission progress" aria-valuenow={done} aria-valuemax={total || 1}>
          <motion.div className="h-full rounded-full bg-gradient-to-r from-accent via-[#6366f1] to-cyan shadow-[0_0_12px_rgba(34,211,238,.6)]" initial={false} animate={{ width: total ? `${Math.max((100 * done) / total, 3)}%` : "3%" }} transition={{ duration: 0.6 }} /></div></div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        <div className="flex items-center gap-1.5 text-fg2">{d.repository?.source_type === "GIT_URL" ? <Github className="h-3.5 w-3.5 shrink-0" /> : <GitBranch className="h-3.5 w-3.5 shrink-0" aria-hidden />}<span className="truncate">{d.repository?.github_owner ? `${d.repository.github_owner}/${d.repository.github_name}` : d.repository?.name}</span></div>
        <div className="flex items-center gap-1.5 text-fg2"><GitBranch className="h-3.5 w-3.5 shrink-0" aria-hidden /><span className="truncate">{d.repository?.default_branch ?? "local copy"}{d.base_commit ? ` @ ${d.base_commit.slice(0, 7)}` : ""}</span></div>
        <div className="flex items-center gap-1.5 text-fg2"><ShieldCheck className="h-3.5 w-3.5 shrink-0" aria-hidden />{current ? <>now: <b style={{ color: guild(current.agent_id).color }}>{guild(current.agent_id).name}</b></> : terminal ? "finished" : "no agent running"}</div>
        <div className="flex items-center gap-1.5 text-fg2"><UserCheck className="h-3.5 w-3.5 shrink-0" aria-hidden />{d.status === "AWAITING_APPROVAL" ? <b className="text-approval">waiting for you</b> : d.status === "AWAITING_HUMAN" ? <b className="text-warning">question for you</b> : d.status === "COMPLETED" ? "approved" : d.status === "REJECTED" ? "rejected" : "not needed yet"}</div>
      </dl>
      {d.status === "AWAITING_HUMAN" && d.pending_human_request && <HumanRequestCard key={d.pending_human_request.id} missionId={d.id} req={d.pending_human_request} onDone={onChanged} />}
      <div className="flex flex-wrap gap-2">
        {d.status === "AWAITING_APPROVAL" && <Button variant="primary" onClick={() => setReview(true)}>Review &amp; decide</Button>}
        {d.status === "PAUSED" && <Button loading={busy === "resume"} onClick={() => act("resume", () => api.missions.resume(d.id), "Mission resumed")}><Play className="h-3.5 w-3.5" aria-hidden />Resume</Button>}
        {["CREATED", "PLANNING", "EXECUTING", "VERIFYING"].includes(d.status) && <Button loading={busy === "pause"} onClick={() => act("pause", () => api.missions.pause(d.id), "Mission paused")}><Pause className="h-3.5 w-3.5" aria-hidden />Pause</Button>}
        {!terminal && <Button variant="danger" loading={busy === "cancel"} onClick={() => { if (confirm("Cancel this mission? Evidence is kept; your repository is not changed.")) void act("cancel", () => api.missions.cancel(d.id), "Mission cancelled"); }}><Ban className="h-3.5 w-3.5" aria-hidden />Cancel</Button>}
        <Link href={`/missions/${d.id}`}><Button variant="ghost">Open workspace</Button></Link>
      </div>
      <Modal open={review} onClose={() => setReview(false)} title="Review and decide" wide>
        {d.status === "AWAITING_APPROVAL" ? <ApprovalPanel d={d} diffs={diffs} tests={tests} findings={findings} verification={verification} onDone={() => { setReview(false); onChanged(); toast("success", "Decision recorded"); }} /> : <p className="text-sm text-fg2">This mission is no longer waiting for approval.</p>}
      </Modal>
    </div>
  );
}
