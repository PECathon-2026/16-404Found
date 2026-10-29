"use client";
import { ArrowRight, Plus } from "lucide-react";
import Link from "next/link";
import { Button, Card, CardHeader, EmptyState, ErrorCard, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { MissionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { MissionCard } from "@/features/missions/MissionCard";

export default function Overview() {
  const { data, error, loading, reload } = useApi<MissionSummary[]>(() => api.missions.list(), [], 4000);
  const ms = data ?? [];
  const attention = ms.filter((m) => m.pending_action);
  const running = ms.filter((m) => ["PLANNING", "EXECUTING", "VERIFYING"].includes(m.status));
  const recent = ms.filter((m) => ["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(m.status)).slice(0, 5);
  const done = ms.filter((m) => m.status === "COMPLETED").length, finished = ms.filter((m) => ["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(m.status)).length;
  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3"><div><h1 className="text-xl font-semibold">Overview</h1><p className="text-sm text-fg3">An autonomous engineering guild that shows its evidence.</p></div>
        <Link href="/missions/new" className="ml-auto"><Button variant="primary"><Plus className="h-4 w-4" aria-hidden />New mission</Button></Link></div>
      {error ? <ErrorCard message={error.message} onRetry={reload} /> : loading ? <Skeleton className="h-40" /> : ms.length === 0 ? (
        <Card><EmptyState title="No missions yet" description="Connect a GitHub repository or a local folder, describe the change, and watch the agents plan, build, test, verify and ask for your approval. Or run a demo scenario to see the whole workflow without an API key."
          action={<div className="flex gap-2"><Link href="/missions/new"><Button variant="primary">Create a mission</Button></Link><Link href="/repositories"><Button>Connect a repository</Button></Link></div>} /></Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-4">{[["Needs you", attention.length], ["Running", running.length], ["Completed", done], ["Finished", finished]].map(([k, v]) => (
            <Card key={String(k)} className="p-4"><div className="text-xs text-fg3">{k}</div><div className="text-2xl font-semibold">{v}</div></Card>))}</div>
          {attention.length > 0 && <section aria-label="Needs your attention"><h2 className="mb-2 text-sm font-semibold">Needs your attention</h2><div className="space-y-2">{attention.map((m) => <MissionCard key={m.id} m={m} />)}</div></section>}
          {running.length > 0 && <section aria-label="Running"><h2 className="mb-2 text-sm font-semibold">Running now</h2><div className="space-y-2">{running.map((m) => <MissionCard key={m.id} m={m} />)}</div></section>}
          <Card><CardHeader title="Recent outcomes" right={<Link href="/history" className="inline-flex items-center gap-1 text-xs text-accent">All history<ArrowRight className="h-3 w-3" /></Link>} />
            <div className="space-y-2 p-3">{recent.length === 0 ? <p className="px-1 text-sm text-fg3">Nothing has finished yet.</p> : recent.map((m) => <MissionCard key={m.id} m={m} />)}</div></Card>
        </>)}
    </div>
  );
}
