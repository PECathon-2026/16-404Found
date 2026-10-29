"use client";
import { ArrowRight, Bug, ChevronDown, ChevronRight, ClipboardCheck, FileDiff, Gavel, Hammer, MessageSquare, Repeat, ShieldAlert, ShieldX, Terminal, UserRound, Wrench } from "lucide-react";
import React, { useMemo, useState } from "react";
import { Badge, Button, EmptyState, Mono, Skeleton, cx, type Tone } from "@/components/ui";
import { api } from "@/lib/api";
import { clock } from "@/lib/format";
import type { DevEvent, Msg, ToolCallRow } from "@/lib/types";
import { SEV_TONE } from "../missions/status";

const AGENT_COLOR: Record<string, string> = { master: "#e3b341", planner: "#6e8bff", developer: "#3fb68b", tester: "#5ad1d9", security: "#e5534b", verifier: "#b48cff", system: "#8a92a0", human: "#e8eaed" };
export const AgentDot = ({ a }: { a: string }) => <span aria-hidden className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: AGENT_COLOR[a] ?? "#8a92a0" }} />;
export const AgentName = ({ a }: { a: string }) => <span className="inline-flex items-center gap-1.5 text-xs font-medium"><AgentDot a={a} />{a}</span>;

type Item = { id: string; at: string; actor: string; kind: string; ev: DevEvent; extra?: DevEvent[] };

/** Fold tool.called/completed/failed of the same call into one card; keep everything else 1:1 with events. */
function toItems(events: DevEvent[]): Item[] {
  const out: Item[] = [];
  const tool = new Map<string, Item>();
  for (const e of events) {
    if (["agent.started", "agent.finished", "task.created", "task.status_changed", "test.run_started", "verification.started", "mission.created"].includes(e.type)) continue;
    if (e.type.startsWith("tool.")) {
      const id = String(e.payload.tool_call_id);
      const it = tool.get(id);
      if (it) { it.extra = [...(it.extra ?? []), e]; continue; }
      const n: Item = { id: e.id, at: e.created_at, actor: e.actor, kind: "tool", ev: e };
      tool.set(id, n); out.push(n); continue;
    }
    out.push({ id: e.id, at: e.created_at, actor: e.actor, kind: e.type, ev: e });
  }
  return out;
}

export function ActivityFeed({ missionId, events, messages, toolCalls, loading, filterAgent, onFilterAgent }: {
  missionId: string; events: DevEvent[]; messages: Msg[]; toolCalls: ToolCallRow[]; loading: boolean; filterAgent: string | null; onFilterAgent: (a: string | null) => void;
}) {
  const items = useMemo(() => toItems(events), [events]);
  const msgById = useMemo(() => new Map(messages.map((m) => [m.id, m])), [messages]);
  const tcById = useMemo(() => new Map(toolCalls.map((t) => [t.id, t])), [toolCalls]);
  const [follow, setFollow] = useState(true);
  const boxRef = React.useRef<HTMLDivElement>(null);
  const shown = items.filter((i) => !filterAgent || i.actor === filterAgent || (i.ev.payload.recipient as string) === filterAgent);
  // Scroll only the feed's own container: scrollIntoView would drag the whole page away from the header and approval panel.
  React.useEffect(() => { const el = boxRef.current; if (follow && el) el.scrollTop = el.scrollHeight; }, [shown.length, follow]);

  if (loading) return <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-10" />)}</div>;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line px-3 py-2">
        <span className="text-xs text-fg3">Agent:</span>
        {[null, "master", "planner", "developer", "tester", "security", "verifier", "system"].map((a) => (
          <button key={a ?? "all"} onClick={() => onFilterAgent(a)} aria-pressed={filterAgent === a}
            className={cx("rounded-full border px-2 py-0.5 text-xs", filterAgent === a ? "border-accent bg-accent/10 text-fg" : "border-line text-fg3 hover:bg-hover")}>{a ?? "all"}</button>))}
        <label className="ml-auto flex items-center gap-1.5 text-xs text-fg3"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />follow live</label>
      </div>
      {shown.length === 0 ? <EmptyState title="Waiting for the first agent step" description="Events appear here the moment agents act: decisions, messages, tool calls, test runs." /> : (
        <div ref={boxRef} role="log" aria-live="polite" aria-relevant="additions" className="max-h-[640px] divide-y divide-line overflow-y-auto">
          {shown.map((i) => <FeedItem key={i.id} item={i} missionId={missionId} msg={i.kind === "message.sent" ? msgById.get(String(i.ev.payload.message_id)) : undefined}
            tc={i.kind === "tool" ? tcById.get(String(i.ev.payload.tool_call_id)) : undefined} />)}
        </div>)}
    </div>
  );
}

function Row({ icon, actor, at, children, tone, tag }: { icon: React.ReactNode; actor: string; at: string; children: React.ReactNode; tone?: Tone; tag?: string }) {
  return (
    <article className="dp-in flex gap-3 px-3 py-2.5">
      <div className="mt-0.5 text-fg3">{icon}</div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><AgentName a={actor} />{tag && <Badge tone={tone ?? "neutral"}>{tag}</Badge>}<time className="ml-auto text-[11px] text-fg3" dateTime={at}>{clock(at)}</time></div>
        <div className="mt-0.5 text-sm text-fg2">{children}</div>
      </div>
    </article>
  );
}

function FeedItem({ item, missionId, msg, tc }: { item: Item; missionId: string; msg?: Msg; tc?: ToolCallRow }) {
  const { ev } = item, p = ev.payload as Record<string, never> & Record<string, unknown>;
  const s = (k: string) => (p[k] == null ? "" : String(p[k]));
  switch (item.kind) {
    case "decision.made":
      return <Row icon={<Gavel className="h-4 w-4" />} actor="master" at={ev.created_at} tag={s("action")} tone={s("action") === "ESCALATE" ? "warning" : s("action") === "RETRY" ? "danger" : "accent"}>
        {s("rationale")} <Badge className="ml-1" title="who decided">{s("forced_by")}</Badge></Row>;
    case "message.sent":
      return <Row icon={<MessageSquare className="h-4 w-4" />} actor={s("sender")} at={ev.created_at} tag={s("type")} tone={msg ? SEV_TONE[msg.severity] : "neutral"}>
        <span className="text-fg3"><ArrowRight className="mr-1 inline h-3 w-3" />{s("recipient")}</span> {s("summary")}
        {msg && msg.evidence_refs.length > 0 && <span className="ml-2 inline-flex flex-wrap gap-1">{msg.evidence_refs.slice(0, 3).map((r, i) => <Badge key={i} title={`${r.kind} ${r.id}`}>{r.kind}</Badge>)}</span>}</Row>;
    case "tool": return <ToolCard item={item} missionId={missionId} tc={tc} />;
    case "file.modified":
      return <Row icon={<FileDiff className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag={s("change_type")} tone="success"><Mono>{s("path")}</Mono> <span className="text-success">+{s("additions")}</span> <span className="text-danger">−{s("deletions")}</span>
        {Array.isArray(p.tamper_flags) && (p.tamper_flags as string[]).length > 0 && <Badge tone="danger" className="ml-2" icon={<ShieldX className="h-3 w-3" />}>test tampering: {(p.tamper_flags as string[]).join(", ")}</Badge>}</Row>;
    case "test.passed": case "test.failed": {
      const sm = (p.summary ?? {}) as Record<string, number>; const ok = item.kind === "test.passed";
      return <Row icon={<ClipboardCheck className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag={`${s("kind")} · ${s("outcome") || (ok ? "GREEN" : "RED")}`} tone={ok ? "success" : "danger"}>
        {sm.total != null ? `${sm.passed ?? 0}/${sm.total} passed${sm.failed ? `, ${sm.failed} failed` : ""}${sm.errored ? `, ${sm.errored} errors` : ""}` : "no summary"}
        {Array.isArray(p.failure_classes) && (p.failure_classes as string[]).map((c) => <Badge key={c} tone="danger" className="ml-1">{c}</Badge>)}
        {p.degraded ? <Badge tone="warning" className="ml-1" title="a fallback runner was used">degraded evidence</Badge> : null}</Row>;
    }
    case "repair.initiated":
      return <Row icon={<Repeat className="h-4 w-4" />} actor="master" at={ev.created_at} tag={`repair cycle ${s("attempt")}`} tone="danger">New evidence changed the plan: a repair task was created
        {p.strategy_change ? <Badge tone="warning" className="ml-2">strategy change required</Badge> : null}{p.failure_fingerprint ? <Mono className="ml-2 text-fg3">{s("failure_fingerprint")}</Mono> : null}</Row>;
    case "finding.created":
      return <Row icon={<ShieldAlert className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag={`${s("severity")} finding`} tone={SEV_TONE[s("severity")]}>{s("category")} at <Mono>{s("file")}:{s("line_start")}</Mono></Row>;
    case "finding.resolved":
      return <Row icon={<ShieldAlert className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag={s("status")} tone="success">{s("category")} at <Mono>{s("file")}:{s("line_start")}</Mono></Row>;
    case "critique.raised": return <Row icon={<Bug className="h-4 w-4" />} actor={s("from") || item.actor} at={ev.created_at} tag="critique" tone="warning"><ArrowRight className="mr-1 inline h-3 w-3" />{s("to")} · {s("summary")}</Row>;
    case "critique.resolved": return <Row icon={<Bug className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag="critique resolved" tone="success">{s("resolution")}</Row>;
    case "verification.completed": {
      const res = (p.results_summary ?? []) as { ac_id: string; status: string }[];
      return <Row icon={<ClipboardCheck className="h-4 w-4" />} actor="verifier" at={ev.created_at} tag={`verification ${s("overall")}`} tone={s("overall") === "PASS" ? "success" : s("overall") === "FAIL" ? "danger" : "warning"}>
        independent process · {res.map((r) => `${r.ac_id}:${r.status}`).join("  ")}{s("error") && <span className="text-danger"> · {s("error")}</span>}</Row>;
    }
    case "mission.status_changed": return <Row icon={<Wrench className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag={`${s("from")} → ${s("to")}`}>{s("reason")}</Row>;
    case "human.input_requested": return <Row icon={<UserRound className="h-4 w-4" />} actor="master" at={ev.created_at} tag={s("kind")} tone="warning">{s("question")}</Row>;
    case "human.input_received": return <Row icon={<UserRound className="h-4 w-4" />} actor="human" at={ev.created_at} tag="answered">{s("option")}</Row>;
    case "approval.requested": return <Row icon={<Hammer className="h-4 w-4" />} actor="master" at={ev.created_at} tag="approval requested" tone="approval">Gate clear. Review the patch and decide.</Row>;
    case "approval.resolved": return <Row icon={<Hammer className="h-4 w-4" />} actor="human" at={ev.created_at} tag={s("decision")} tone={s("decision") === "APPROVED" ? "success" : "danger"}>decision recorded against the exact patch hash</Row>;
    case "policy.denied": return <Row icon={<ShieldX className="h-4 w-4" />} actor={item.actor} at={ev.created_at} tag="blocked by policy" tone="danger"><Mono>{s("tool")}</Mono> {s("reason")}</Row>;
    case "budget.warning": return <Row icon={<ShieldAlert className="h-4 w-4" />} actor="system" at={ev.created_at} tag="budget" tone="warning">{s("resource")} at {s("pct")}% ({s("used")}/{s("limit")})</Row>;
    case "mission.completed": return <Row icon={<ClipboardCheck className="h-4 w-4" />} actor="master" at={ev.created_at} tag="completed" tone="success">The approved patch was applied.</Row>;
    case "mission.failed": return <Row icon={<ShieldX className="h-4 w-4" />} actor="system" at={ev.created_at} tag="failed" tone="danger">{s("reason")}</Row>;
    default: return null;
  }
}

function ToolCard({ item, missionId, tc }: { item: Item; missionId: string; tc?: ToolCallRow }) {
  const all = [item.ev, ...(item.extra ?? [])];
  const last = all[all.length - 1];
  const status = last.type === "tool.called" ? "RUNNING" : last.type === "tool.completed" ? "OK" : last.type === "policy.denied" ? "DENIED" : "ERROR";
  const p = last.payload; const first = item.ev.payload;
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<string | null>(null);
  const tone: Tone = status === "OK" ? "success" : status === "RUNNING" ? "running" : status === "DENIED" ? "warning" : "danger";
  async function expand() {
    setOpen(!open);
    if (!open && tc?.id && full == null) { try { const r = await api.missions.toolCall(missionId, tc.id); setFull(r.full_output ?? r.output_excerpt ?? ""); } catch { setFull(tc.output_excerpt ?? ""); } }
  }
  return (
    <article className="dp-in px-3 py-2">
      <button onClick={expand} aria-expanded={open} className="flex w-full items-start gap-3 text-left">
        <Terminal className="mt-0.5 h-4 w-4 shrink-0 text-fg3" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><AgentName a={item.actor} /><Mono className="font-semibold">{String(first.tool ?? p.tool)}</Mono>
            <Badge tone={tone} className={status === "RUNNING" ? "dp-pulse" : ""}>{status}</Badge>
            {p.exit_code != null && <Badge tone={p.exit_code === 0 ? "neutral" : "danger"}>exit {String(p.exit_code)}</Badge>}
            {p.duration_ms != null && <span className="text-[11px] text-fg3">{String(p.duration_ms)} ms</span>}
            {(tc?.redactions ?? 0) > 0 && <Badge tone="warning" title="secrets were masked in this output">{tc?.redactions} redacted</Badge>}
            <time className="ml-auto text-[11px] text-fg3">{clock(item.ev.created_at)}</time></div>
          <p className="truncate font-mono text-[12px] text-fg3">{String(first.args_summary ?? "")}</p>
        </div>
        {open ? <ChevronDown className="mt-1 h-4 w-4 text-fg3" /> : <ChevronRight className="mt-1 h-4 w-4 text-fg3" />}
      </button>
      {open && <div className="ml-7 mt-2"><TerminalOutput text={full ?? tc?.output_excerpt ?? ""} loading={full == null && !!tc} policy={tc?.policy_reason} /></div>}
    </article>
  );
}

export function TerminalOutput({ text, loading, policy }: { text: string; loading?: boolean; policy?: string | null }) {
  if (loading) return <Skeleton className="h-16" />;
  if (!text && !policy) return <p className="text-xs text-fg3">No output yet.</p>;
  return (
    <div role="region" aria-label="Tool output" className="rounded-md border border-line bg-canvas">
      {policy && <p className="border-b border-line px-3 py-1.5 text-xs text-warning">Policy: {policy}</p>}
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[12px] leading-5 text-fg2">{text}</pre>
      <div className="flex justify-end border-t border-line px-2 py-1"><Button size="sm" variant="ghost" onClick={() => navigator.clipboard?.writeText(text)}>Copy</Button></div>
    </div>
  );
}
