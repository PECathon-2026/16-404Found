"use client";
import { useState } from "react";
import { Card, CardHeader, EmptyState, Skeleton, inputCls } from "@/components/ui";
import { AGENTS, AgentNetworkGraph } from "@/features/agents/agents";
import { api } from "@/lib/api";
import type { MissionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useMissionLive } from "@/lib/useMission";

function Network({ id }: { id: string }) {
  const live = useMissionLive(id);
  return <AgentNetworkGraph detail={live.detail} messages={live.messages} events={live.events} />;
}
export default function Page() {
  const { data, loading } = useApi<MissionSummary[]>(() => api.missions.list(), [], 5000);
  const [sel, setSel] = useState<string | null>(null);
  const ms = data ?? [];
  const current = sel ?? ms.find((m) => ["PLANNING", "EXECUTING", "VERIFYING", "AWAITING_HUMAN", "AWAITING_APPROVAL"].includes(m.status))?.id ?? ms[0]?.id ?? null;
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3"><div><h1 className="text-xl font-semibold">Agent network</h1><p className="text-sm text-fg3">Real message flow between agents for a mission.</p></div>
        <select aria-label="Mission" className={`${inputCls} ml-auto max-w-xs`} value={current ?? ""} onChange={(e) => setSel(e.target.value)}>{ms.map((m) => <option key={m.id} value={m.id}>{m.title} · {m.status}</option>)}</select></div>
      <Card><CardHeader title="Topology" />{loading ? <Skeleton className="m-4 h-64" /> : current ? <Network key={current} id={current} /> : <EmptyState title="No missions yet" description="Start a mission to see the agents coordinate." />}</Card>
      <Card><CardHeader title="Roles" /><ul className="divide-y divide-line">{AGENTS.map((a) => <li key={a.id} className="flex items-center gap-3 px-4 py-2.5 text-sm"><span style={{ color: a.color }}><a.Icon className="h-4 w-4" aria-hidden /></span><b className="w-44">{a.name}</b><span className="text-fg3">{a.role}</span></li>)}</ul></Card>
    </div>
  );
}
