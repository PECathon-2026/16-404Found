"use client";
import { FileDown, FileText } from "lucide-react";
import Link from "next/link";
import { Badge, Card, EmptyState, ErrorCard, Skeleton } from "@/components/ui";
import { MissionStatusBadge } from "@/features/missions/status";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { MissionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export default function Page() {
  const { data, error, loading, reload } = useApi<MissionSummary[]>(() => api.missions.list(), [], 8000);
  const done = (data ?? []).filter((m) => ["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(m.status));
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div><h1 className="text-xl font-semibold">Reports</h1><p className="text-sm text-fg3">Final evidence reports: verified outcomes kept separate from unresolved items, agent claims and model claims.</p></div>
      <Card>{error ? <div className="p-4"><ErrorCard message={error.message} onRetry={reload} /></div> : loading ? <Skeleton className="m-4 h-16" /> : done.length === 0 ? (
        <EmptyState icon={<FileText className="h-6 w-6" />} title="No finished missions yet" description="A report is produced when a mission completes, fails, is rejected or is cancelled." />
      ) : <ul className="divide-y divide-line">{done.map((m) => (
        <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3"><div className="min-w-0 flex-1"><Link href={`/missions/${m.id}`} className="text-sm font-medium hover:underline">{m.title}</Link><div className="text-xs text-fg3">{m.repository.name} · {timeAgo(m.updated_at)}</div></div>
          <MissionStatusBadge status={m.status} />{m.mode === "scripted" && <Badge>demo model</Badge>}
          <a className="inline-flex h-7 items-center gap-1 rounded-md border border-line-strong px-2 text-xs hover:bg-hover" href={api.missions.reportMdUrl(m.id)} target="_blank" rel="noreferrer"><FileDown className="h-3.5 w-3.5" />Markdown</a>
          <a className="inline-flex h-7 items-center gap-1 rounded-md border border-line-strong px-2 text-xs hover:bg-hover" href={api.missions.patchUrl(m.id)} target="_blank" rel="noreferrer">Patch</a></li>))}</ul>}</Card>
    </div>
  );
}
