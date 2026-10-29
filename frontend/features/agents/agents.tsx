"use client";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { BadgeCheck, Compass, Crown, FlaskConical, Hammer, ShieldCheck, Lock } from "lucide-react";
import React, { useMemo, useSyncExternalStore } from "react";

// Time as an external store: render stays pure and animated edges expire without extra events.
const subscribeTick = (cb: () => void) => { const t = setInterval(cb, 5000); return () => clearInterval(t); };
const tickSnapshot = () => Math.floor(Date.now() / 5000);
const useNow = () => useSyncExternalStore(subscribeTick, tickSnapshot, () => 0) * 5000;
import { Badge, Card, CardHeader, cx, EmptyState, Mono } from "@/components/ui";
import type { AgentRow, DevEvent, Metrics, MissionDetail, Msg } from "@/lib/types";

export const AGENTS = [
  { id: "master", name: "Shogun", role: "Orchestrator", color: "#e3b341", Icon: Crown }, { id: "planner", name: "Architect", role: "Planning", color: "#6e8bff", Icon: Compass },
  { id: "developer", name: "Engineer", role: "Implementation", color: "#3fb68b", Icon: Hammer }, { id: "tester", name: "QA Engineer", role: "Testing", color: "#5ad1d9", Icon: FlaskConical },
  { id: "security", name: "Security Engineer", role: "Review & security", color: "#e5534b", Icon: ShieldCheck }, { id: "verifier", name: "Independent Verifier", role: "Separate process", color: "#b48cff", Icon: BadgeCheck },
] as const;

export function AgentCard({ a, onClick, active }: { a: AgentRow; onClick?: () => void; active?: boolean }) {
  const meta = AGENTS.find((x) => x.id === a.agent_id)!;
  const running = a.status === "thinking" || a.status === "tool";
  return (
    <button onClick={onClick} aria-pressed={active} className={cx("flex w-full items-center gap-3 rounded-lg border bg-surface px-3 py-2 text-left hover:bg-hover", active ? "border-accent" : "border-line")}>
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md" style={{ background: `${meta.color}22`, color: meta.color }}><meta.Icon className="h-4 w-4" aria-hidden /></span>
      <span className="min-w-0 flex-1"><span className="flex items-center gap-1.5 text-sm font-medium">{meta.name}{a.agent_id === "verifier" && <Lock className="h-3 w-3 text-fg3" aria-label="isolated process" />}</span>
        <span className="block truncate text-[11px] text-fg3">{meta.role} · {a.executions} run{a.executions === 1 ? "" : "s"}{a.last_error ? ` · last error: ${a.last_error.slice(0, 40)}` : ""}</span></span>
      <Badge tone={running ? "running" : a.last_error ? "danger" : "neutral"} className={running ? "dp-pulse" : ""}>{running ? "working" : "idle"}</Badge>
    </button>
  );
}

function AgentNode({ data }: NodeProps<Node<{ a: (typeof AGENTS)[number]; row?: AgentRow; failed: number }>>) {
  const { a, row, failed } = data;
  const running = row?.status === "thinking";
  return (
    <div className={cx("w-[170px] rounded-xl border bg-elevated px-3 py-2 shadow-sm", failed ? "border-danger" : running ? "border-running" : "border-line-strong", a.id === "verifier" && "border-dashed")}>
      <Handle type="target" position={Position.Top} className="!opacity-0" /><Handle type="source" position={Position.Bottom} className="!opacity-0" />
      <Handle id="l" type="target" position={Position.Left} className="!opacity-0" /><Handle id="r" type="source" position={Position.Right} className="!opacity-0" />
      <div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-md" style={{ background: `${a.color}22`, color: a.color }}><a.Icon className="h-4 w-4" aria-hidden /></span>
        <div className="leading-tight"><div className="text-xs font-semibold">{a.name}</div><div className="text-[10px] text-fg3">{a.id === "verifier" ? "isolated process" : a.role}</div></div></div>
      <div className="mt-1.5 flex items-center justify-between text-[10px]"><span className={running ? "dp-pulse text-running" : "text-fg3"}>{running ? "working" : "idle"}</span><span className="text-fg3">{row?.executions ?? 0} runs</span>{failed > 0 && <span className="text-danger">{failed} failed</span>}</div>
    </div>
  );
}
const nodeTypes = { agent: AgentNode };
const POS: Record<string, { x: number; y: number }> = { master: { x: 250, y: 130 }, planner: { x: 0, y: 0 }, developer: { x: 500, y: 0 }, tester: { x: 0, y: 260 }, security: { x: 250, y: 300 }, verifier: { x: 500, y: 260 } };

/** Edges come only from persisted messages: solid = control flow, dashed = peer critique/feedback loop. */
export function AgentNetworkGraph({ detail, messages, events, onSelectAgent }: { detail: MissionDetail | null; messages: Msg[]; events: DevEvent[]; onSelectAgent?: (a: string) => void }) {
  const now = useNow();
  const { nodes, edges, loops } = useMemo(() => {
    const rows = new Map((detail?.agents ?? []).map((a) => [a.agent_id, a]));
    const failedBy = new Map<string, number>();
    events.filter((e) => e.type === "tool.failed" && now - new Date(e.created_at).getTime() < 3600_000).forEach((e) => failedBy.set(e.actor, (failedBy.get(e.actor) ?? 0) + 1));
    const nodes: Node[] = AGENTS.map((a) => ({ id: a.id, type: "agent", position: POS[a.id], data: { a, row: rows.get(a.id), failed: failedBy.get(a.id) ?? 0 }, draggable: false }));
    const counts = new Map<string, { n: number; types: Set<string>; peer: boolean }>();
    const known = new Set<string>(AGENTS.map((a) => a.id));
    for (const m of messages) {
      if (!known.has(m.sender) || !known.has(m.recipient)) continue;
      const k = `${m.sender}>${m.recipient}`;
      const c = counts.get(k) ?? { n: 0, types: new Set(), peer: false };
      c.n++; c.types.add(m.type); c.peer ||= ["CRITIQUE", "CRITIQUE_RESPONSE", "QUESTION"].includes(m.type); counts.set(k, c);
    }
    const lastMsgAt = messages.length ? new Date(messages[messages.length - 1].created_at).getTime() : 0;
    const edges: Edge[] = [...counts.entries()].map(([k, c]) => {
      const [s, t] = k.split(">");
      return { id: k, source: s, target: t, label: `${[...c.types].slice(0, 2).join(", ")} ×${c.n}`, animated: c.peer && now - lastMsgAt < 15000,
        style: { stroke: c.peer ? "var(--st-warning)" : "var(--border-strong)", strokeWidth: Math.min(1 + c.n / 3, 4), strokeDasharray: c.peer ? "6 4" : undefined },
        labelStyle: { fontSize: 10, fill: "var(--text-muted)" }, labelBgStyle: { fill: "var(--bg-canvas)" } };
    });
    return { nodes, edges, loops: detail?.counters.repair_cycles ?? 0 };
  }, [detail, messages, events, now]);

  if (!detail) return <EmptyState title="No mission selected" />;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs text-fg3">
        <span>Solid = control · dashed amber = peer critique / feedback</span>{loops > 0 && <Badge tone="danger">repair ×{loops}</Badge>}{messages.length === 0 && <span>No agent messages yet.</span>}</div>
      <div className="h-[420px] border-t border-line" role="img" aria-label={`Agent network with ${messages.length} messages`}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.15 }} nodesConnectable={false} proOptions={{ hideAttribution: true }}
          onNodeClick={(_, n) => onSelectAgent?.(n.id)}><Background gap={24} /></ReactFlow></div>
      <table className="sr-only"><caption>Agent message flows</caption><thead><tr><th>From</th><th>To</th><th>Count</th></tr></thead>
        <tbody>{edges.map((e) => <tr key={e.id}><td>{e.source}</td><td>{e.target}</td><td>{String(e.label)}</td></tr>)}</tbody></table>
    </div>
  );
}

const Row = ({ k, v }: { k: string; v: React.ReactNode }) => <div className="flex justify-between gap-2 py-1 text-xs"><dt className="text-fg3">{k}</dt><dd className="text-right font-medium">{v}</dd></div>;

export function MetricsPanel({ m, d }: { m: Metrics | null; d: MissionDetail | null }) {
  const lim = d?.budgets.tokens;
  const pct = lim ? Math.min(100, Math.round((100 * lim.used) / lim.limit)) : null;
  return (
    <Card><CardHeader title="Metrics" sub="from persisted rows; “no data” means not measured" />
      <div className="px-4 py-2">
        {lim && <div className="mb-2"><div className="flex justify-between text-xs"><span className="text-fg3">Token budget</span><span>{lim.used.toLocaleString()} / {lim.limit.toLocaleString()}</span></div>
          <div className="mt-1 h-1.5 overflow-hidden rounded bg-hover" role="progressbar" aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100} aria-label="Token budget used"><div className={cx("h-full", (pct ?? 0) >= 80 ? "bg-warning" : "bg-accent")} style={{ width: `${pct}%` }} /></div></div>}
        <dl className="divide-y divide-line">
          <Row k="Repair cycles" v={m?.repair_cycles ?? d?.counters.repair_cycles ?? "no data"} /><Row k="Tool calls" v={m ? `${m.tool_calls} (${m.tool_denied} denied, ${m.tool_errors} errors)` : "no data"} />
          <Row k="Distinct developer tools" v={m?.distinct_developer_tools ?? "no data"} /><Row k="Redundant call rate" v={m?.redundant_tool_call_rate != null ? `${Math.round(m.redundant_tool_call_rate * 100)}%` : "no data"} />
          <Row k="Agent messages" v={m?.messages ?? "no data"} /><Row k="Open findings" v={m ? `${m.findings.open} of ${m.findings.total}` : "no data"} />
          <Row k="Cost" v={<span title={m?.cost_note}>{m?.cost_usd != null ? `$${m.cost_usd.toFixed(2)}` : "not estimated"}</span>} /></dl></div></Card>
  );
}
export { Mono };
