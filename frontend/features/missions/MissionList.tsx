"use client";
import { Plus, Search } from "lucide-react";
import Link from "next/link";
import React, { useState } from "react";
import { Button, EmptyState, ErrorCard, Skeleton, inputCls } from "@/components/ui";
import { api } from "@/lib/api";
import type { MissionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { MissionCard } from "./MissionCard";

const FILTERS = ["all", "needs you", "running", "done", "stopped"] as const;
export function MissionList({ terminalOnly, title = "Missions" }: { terminalOnly?: boolean; title?: string }) {
  const { data, error, loading, reload } = useApi<MissionSummary[]>(() => api.missions.list(), [], 4000);
  const [q, setQ] = useState("");
  const [f, setF] = useState<(typeof FILTERS)[number]>("all");
  const rows = (data ?? []).filter((m) => {
    if (terminalOnly && !["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(m.status)) return false;
    if (q && !`${m.title} ${m.repository.name}`.toLowerCase().includes(q.toLowerCase())) return false;
    if (f === "needs you") return !!m.pending_action;
    if (f === "running") return ["PLANNING", "EXECUTING", "VERIFYING"].includes(m.status);
    if (f === "done") return m.status === "COMPLETED";
    if (f === "stopped") return ["REJECTED", "FAILED", "CANCELLED"].includes(m.status);
    return true;
  });
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-semibold">{title}</h1>
        <Link href="/missions/new" className="ml-auto"><Button variant="primary"><Plus className="h-4 w-4" aria-hidden />New mission</Button></Link></div>
      <div className="flex flex-wrap gap-2"><div className="relative min-w-[200px] flex-1"><Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-fg3" aria-hidden />
        <input className={`${inputCls} pl-8`} placeholder="Search missions" aria-label="Search missions" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <div role="group" aria-label="Filter" className="flex gap-1">{FILTERS.map((x) => <button key={x} aria-pressed={f === x} onClick={() => setF(x)} className={`rounded-md border px-2.5 text-sm ${f === x ? "border-accent bg-accent/10" : "border-line text-fg3 hover:bg-hover"}`}>{x}</button>)}</div></div>
      {error ? <ErrorCard message={error.message} onRetry={reload} /> : loading ? <div className="space-y-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div> : rows.length === 0 ? (
        <EmptyState title={(data ?? []).length === 0 ? "No missions yet" : "No missions match"} description={(data ?? []).length === 0 ? "Describe a change in plain language and DevPilot will plan, build, test, verify and ask for your approval." : "Try a different filter."}
          action={(data ?? []).length === 0 ? <Link href="/missions/new"><Button variant="primary">Create your first mission</Button></Link> : undefined} />
      ) : <div className="space-y-2">{rows.map((m) => <MissionCard key={m.id} m={m} />)}</div>}
    </div>
  );
}
