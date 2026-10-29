"use client";
import { Background, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ListTree, Network } from "lucide-react";
import React, { useMemo, useState } from "react";
import { Badge, Button, EmptyState, Mono, cx } from "@/components/ui";
import type { Criterion, Task } from "@/lib/types";
import { CRIT_TONE, TASK_TONE } from "../missions/status";

export function CriteriaList({ criteria, objectives }: { criteria: Criterion[]; objectives: string[] }) {
  if (criteria.length === 0) return <p className="px-4 py-3 text-sm text-fg3">Acceptance criteria appear once the Architect has inspected the repository.</p>;
  return (
    <div>
      {objectives.length > 0 && <ul className="list-disc space-y-0.5 px-8 py-2 text-sm text-fg2">{objectives.map((o, i) => <li key={i}>{o}</li>)}</ul>}
      <ul className="divide-y divide-line">{criteria.map((c) => (
        <li key={c.id} className="flex items-start gap-2 px-4 py-2.5">
          <Mono className="mt-0.5 font-semibold">{c.id}</Mono>
          <div className="min-w-0 flex-1"><p className="text-sm">{c.text}</p>
            <p className="mt-0.5 text-[11px] text-fg3">checked by <b>{c.verification_method.replace("_", " ")}</b>{c.verification_method === "command" && Array.isArray(c.verification.argv) ? <> · <Mono>{(c.verification.argv as string[]).join(" ")}</Mono></> : null}
              {c.verification_method === "manual_review" && " · needs your acknowledgement (cannot be machine-verified)"}</p></div>
          <Badge tone={CRIT_TONE[c.status]}>{c.status}</Badge></li>))}</ul>
    </div>
  );
}

function TaskNode({ data }: NodeProps<Node<{ t: Task; sel: boolean }>>) {
  const t = data.t;
  return (
    <div className={cx("w-[210px] rounded-lg border bg-elevated px-3 py-2 text-xs shadow-sm", data.sel ? "border-accent" : "border-line-strong", t.status === "SUPERSEDED" && "opacity-50")}>
      <Handle type="target" position={Position.Left} className="!bg-line-strong" />
      <div className="flex items-center justify-between gap-2"><span className={cx("font-mono font-semibold", t.status === "SUPERSEDED" && "line-through")}>{t.key}</span><Badge tone={TASK_TONE[t.status]} className={t.status === "IN_PROGRESS" ? "dp-pulse" : ""}>{t.status.replace("_", " ")}</Badge></div>
      <p className="mt-1 line-clamp-2 text-fg2">{t.title}</p>
      <p className="mt-1 text-fg3">{t.kind}{t.assignee ? ` · ${t.assignee}` : ""}{t.retries > 1 ? ` · attempt ${t.retries}` : ""}</p>
      <Handle type="source" position={Position.Right} className="!bg-line-strong" />
    </div>
  );
}
const nodeTypes = { task: TaskNode };

export function TaskDependencyGraph({ tasks, onSelect, selected }: { tasks: Task[]; onSelect?: (t: Task) => void; selected?: string | null }) {
  const [mode, setMode] = useState<"graph" | "list">("graph");
  const { nodes, edges } = useMemo(() => {
    const depth = new Map<string, number>();
    const byId = new Map(tasks.map((t) => [t.id, t]));
    const d = (t: Task, seen = new Set<string>()): number => {
      if (depth.has(t.id)) return depth.get(t.id)!;
      if (seen.has(t.id)) return 0;
      seen.add(t.id);
      const v = t.depends_on.length ? 1 + Math.max(...t.depends_on.map((x) => (byId.get(x) ? d(byId.get(x)!, seen) : 0))) : 0;
      depth.set(t.id, v); return v;
    };
    const col = new Map<number, number>();
    const nodes: Node[] = tasks.map((t) => {
      const x = d(t); const y = col.get(x) ?? 0; col.set(x, y + 1);
      return { id: t.id, type: "task", position: { x: x * 260, y: y * 100 }, data: { t, sel: selected === t.id }, draggable: false };
    });
    const edges: Edge[] = tasks.flatMap((t) => t.depends_on.map((s) => ({ id: `${s}-${t.id}`, source: s, target: t.id, animated: t.status === "IN_PROGRESS", style: { stroke: "var(--border-strong)" } })));
    return { nodes, edges };
  }, [tasks, selected]);

  if (tasks.length === 0) return <EmptyState title="Plan not created yet" description="Tasks and their dependencies appear after the planner submits a validated plan." />;
  return (
    <div>
      <div className="flex items-center justify-between px-4 py-2"><span className="text-xs text-fg3">{tasks.filter((t) => t.status === "DONE").length} of {tasks.filter((t) => t.status !== "SUPERSEDED").length} tasks done</span>
        <div className="flex gap-1"><Button size="sm" variant={mode === "graph" ? "secondary" : "ghost"} onClick={() => setMode("graph")}><Network className="h-3.5 w-3.5" aria-hidden />Graph</Button>
          <Button size="sm" variant={mode === "list" ? "secondary" : "ghost"} onClick={() => setMode("list")}><ListTree className="h-3.5 w-3.5" aria-hidden />List</Button></div></div>
      {mode === "graph" ? (
        <div className="h-[340px] border-t border-line" aria-label="Task dependency graph (switch to List for a screen-reader friendly view)">
          <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }} nodesConnectable={false} proOptions={{ hideAttribution: true }}
            onNodeClick={(_, n) => { const t = tasks.find((x) => x.id === n.id); if (t) onSelect?.(t); }}><Background gap={20} /></ReactFlow>
        </div>
      ) : (
        <ul className="divide-y divide-line border-t border-line">{tasks.map((t) => (
          <li key={t.id} className="flex items-start gap-3 px-4 py-2.5"><Mono className="font-semibold">{t.key}</Mono>
            <div className="min-w-0 flex-1"><p className={cx("text-sm", t.status === "SUPERSEDED" && "line-through opacity-60")}>{t.title}</p>
              <p className="text-[11px] text-fg3">{t.kind}{t.assignee ? ` · ${t.assignee}` : ""}{t.depends_on.length ? ` · after ${t.depends_on.map((d) => tasks.find((x) => x.id === d)?.key).filter(Boolean).join(", ")}` : ""}{t.criteria_refs.length ? ` · serves ${t.criteria_refs.join(", ")}` : ""}</p>
              {t.failure_context && <p className="mt-0.5 text-[11px] text-danger">repair evidence: {String((t.failure_context as { kind?: string }).kind ?? "failure")}</p>}</div>
            <Badge tone={TASK_TONE[t.status]}>{t.status.replace("_", " ")}</Badge></li>))}</ul>)}
    </div>
  );
}
