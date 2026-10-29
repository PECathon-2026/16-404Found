"use client";
import { Pause, Play, SkipForward } from "lucide-react";
import React, { useEffect, useMemo, useState } from "react";
import { Badge, Button, EmptyState, Mono, type Tone } from "@/components/ui";
import { api } from "@/lib/api";
import { clock } from "@/lib/format";
import type { DevEvent } from "@/lib/types";

const KEY = new Set(["mission.status_changed", "decision.made", "repair.initiated", "test.failed", "test.passed", "verification.completed", "approval.requested", "approval.resolved",
  "human.input_requested", "human.input_received", "finding.created", "finding.resolved", "mission.completed", "mission.failed", "budget.warning", "task.superseded"]);

function label(e: DevEvent): { text: string; tone: Tone } {
  const p = e.payload as Record<string, unknown>; const s = (k: string) => String(p[k] ?? "");
  switch (e.type) {
    case "mission.status_changed": return { text: `${s("from")} → ${s("to")}${p.reason ? `: ${s("reason")}` : ""}`, tone: "accent" };
    case "decision.made": return { text: `${s("action")}: ${s("rationale")}`.slice(0, 180), tone: s("action") === "RETRY" ? "danger" : "accent" };
    case "repair.initiated": return { text: `Repair cycle ${s("attempt")}${p.strategy_change ? " (strategy change)" : ""}`, tone: "danger" };
    case "test.failed": return { text: `${s("kind")} run failed${Array.isArray(p.failure_classes) ? ` (${(p.failure_classes as string[]).join(", ")})` : ""}`, tone: "danger" };
    case "test.passed": return { text: `${s("kind")} run passed`, tone: "success" };
    case "verification.completed": return { text: `Independent verification: ${s("overall")}`, tone: s("overall") === "PASS" ? "success" : "warning" };
    case "finding.created": return { text: `${s("severity")} finding: ${s("category")}`, tone: "warning" };
    case "finding.resolved": return { text: `Finding ${s("status").toLowerCase()}: ${s("category")}`, tone: "success" };
    case "approval.requested": return { text: "Approval requested", tone: "approval" };
    case "approval.resolved": return { text: `Human decision: ${s("decision")}`, tone: s("decision") === "APPROVED" ? "success" : "danger" };
    case "human.input_requested": return { text: `Question for the human: ${s("question")}`.slice(0, 160), tone: "warning" };
    case "human.input_received": return { text: `Human answered (${s("option")})`, tone: "neutral" };
    case "mission.completed": return { text: "Patch applied", tone: "success" };
    case "mission.failed": return { text: `Failed: ${s("reason")}`, tone: "danger" };
    case "budget.warning": return { text: `Budget ${s("pct")}% (${s("resource")})`, tone: "warning" };
    default: return { text: e.type, tone: "neutral" };
  }
}

/** High-level story. Repair loops are grouped: each `repair.initiated` opens a "cycle" that closes at the next test.passed. */
export function MissionTimeline({ events }: { events: DevEvent[] }) {
  const key = useMemo(() => events.filter((e) => KEY.has(e.type)), [events]);
  const t0 = events[0] ? new Date(events[0].created_at).getTime() : 0;
  if (key.length === 0) return <EmptyState title="Nothing has happened yet" description="Milestones (decisions, repair cycles, verification, approvals) appear here as they occur." />;
  return (
    <ol className="space-y-0 px-4 py-3">
      {key.map((e) => { const l = label(e); const secs = Math.round((new Date(e.created_at).getTime() - t0) / 1000);
        return (
          <li key={e.id} className="relative flex gap-3 border-l border-line-strong pb-3 pl-4">
            <span aria-hidden className="absolute -left-[4.5px] top-1.5 h-2 w-2 rounded-full bg-accent" />
            <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Badge tone={l.tone}>{e.type.split(".")[0]}</Badge><span className="text-[11px] text-fg3">+{secs}s · {clock(e.created_at)}</span></div>
              <p className="mt-0.5 text-sm text-fg2">{l.text}</p></div></li>); })}
    </ol>
  );
}

/** Replays persisted events through the same renderer. Always labelled "Replay, not live". */
export function ExecutionReplay({ missionId, onFrame }: { missionId: string; onFrame: (events: DevEvent[] | null) => void }) {
  const [all, setAll] = useState<DevEvent[] | null>(null);
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(4);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.missions.replay(missionId).then((e) => { setAll(e); setI(e.length); }).catch((e) => setErr(e.message)); }, [missionId]);
  useEffect(() => {
    if (!playing || !all) return;
    const t = setInterval(() => setI((v) => { if (v >= all.length) { setPlaying(false); return v; } return v + 1; }), 1000 / speed);
    return () => clearInterval(t);
  }, [playing, all, speed]);
  useEffect(() => { if (all) onFrame(all.slice(0, i)); }, [all, i, onFrame]);
  useEffect(() => () => onFrame(null), [onFrame]);
  if (err) return <p role="alert" className="text-sm text-danger">{err}</p>;
  if (!all) return <p className="text-sm text-fg3">Loading replay…</p>;
  const cur = all[Math.max(0, i - 1)];
  return (
    <div className="space-y-2 rounded-lg border border-warning/30 bg-warning/5 p-3">
      <div className="flex flex-wrap items-center gap-2"><Badge tone="warning">Replay: not live</Badge><span className="text-xs text-fg3">built from {all.length} persisted events</span></div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => { if (i >= all.length) setI(0); setPlaying(!playing); }} aria-label={playing ? "Pause replay" : "Play replay"}>{playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}</Button>
        <Button size="sm" variant="ghost" aria-label="Next event" onClick={() => setI(Math.min(all.length, i + 1))}><SkipForward className="h-3.5 w-3.5" /></Button>
        <input type="range" min={0} max={all.length} value={i} onChange={(e) => { setPlaying(false); setI(Number(e.target.value)); }} aria-label="Replay position" aria-valuetext={`Event ${i} of ${all.length}`} className="flex-1" />
        <select aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="rounded border border-line-strong bg-canvas px-1 py-1 text-xs">{[1, 4, 16].map((s) => <option key={s} value={s}>{s}×</option>)}</select>
      </div>
      <p className="text-xs text-fg3">Event {i} of {all.length}{cur ? <> · <Mono>{cur.type}</Mono> · {clock(cur.created_at)}</> : null}</p>
    </div>
  );
}
