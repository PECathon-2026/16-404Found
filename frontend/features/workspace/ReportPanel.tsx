"use client";
import { Download, ExternalLink, FileDown, RotateCcw } from "lucide-react";
import React, { useState } from "react";
import { Badge, Button, ErrorCard, Skeleton, Mono, EmptyState } from "@/components/ui";
import { api } from "@/lib/api";
import type { MissionDetail, Outcome, OutcomeItem } from "@/lib/types";
import { useApi } from "@/lib/useApi";

function Col({ title, items, tone, empty }: { title: string; items: OutcomeItem[]; tone: "success" | "danger" | "warning" | "neutral"; empty: string }) {
  return (
    <section aria-label={title} className="rounded-lg border border-line bg-surface">
      <h4 className="flex items-center justify-between border-b border-line px-3 py-2 text-xs font-semibold"><span>{title}</span><Badge tone={tone}>{items.length}</Badge></h4>
      {items.length === 0 ? <p className="px-3 py-2 text-xs text-fg3">{empty}</p> : <ul className="divide-y divide-line">{items.map((i, k) => (
        <li key={`${i.id}-${k}`} className="px-3 py-2 text-xs"><p className="text-fg">{i.text}</p><p className="mt-0.5 text-fg3">{i.source ?? i.status ?? ""}{i.why ? ` · ${i.why}` : ""}{i.note ? ` · ${i.note}` : ""}</p></li>))}</ul>}
    </section>
  );
}

/** EvidencePartition: what is verified vs. unresolved vs. only claimed (PS-001: separate verified outcomes from assumptions/model claims). */
export function ReportPanel({ d, onChanged }: { d: MissionDetail; onChanged: () => void }) {
  const { data, error, loading, reload } = useApi(() => api.missions.report(d.id), [d.id, d.status], d.status === "COMPLETED" || d.status === "FAILED" ? undefined : 8000);
  const [rb, setRb] = useState<string | null>(null);
  if (loading) return <Skeleton className="m-4 h-40" />;
  if (error) return <div className="p-4"><ErrorCard message={error.message} onRetry={reload} /></div>;
  const o: Outcome | undefined = data?.report;
  if (!o) return <EmptyState title="No report yet" />;
  const a = o.applied;
  return (
    <div className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={o.terminal_status === "COMPLETED" ? "success" : ["REJECTED", "FAILED"].includes(o.terminal_status) ? "danger" : "warning"}>{data?.final ? o.terminal_status : `in progress (${o.terminal_status})`}</Badge>
        {!data?.final && <span className="text-xs text-fg3">Live snapshot from current evidence; it becomes final when the mission ends.</span>}
        {o.mode === "scripted" && <Badge title="scripted model replay">demo model</Badge>}
        <div className="ml-auto flex gap-2"><a className="inline-flex h-7 items-center gap-1 rounded-md border border-line-strong px-2 text-xs hover:bg-hover" href={api.missions.reportMdUrl(d.id)} target="_blank" rel="noreferrer"><FileDown className="h-3.5 w-3.5" />Report (md)</a>
          <a className="inline-flex h-7 items-center gap-1 rounded-md border border-line-strong px-2 text-xs hover:bg-hover" href={api.missions.patchUrl(d.id)} target="_blank" rel="noreferrer"><Download className="h-3.5 w-3.5" />Patch</a></div></div>
      {o.reason && <p className="text-sm text-fg2">{o.reason}</p>}
      <dl className="grid gap-2 text-xs sm:grid-cols-4">
        <div><dt className="text-fg3">Baseline</dt><dd>{o.baseline ? `${o.baseline.outcome} ${o.baseline.passed}/${o.baseline.total}` : "—"}</dd></div>
        <div><dt className="text-fg3">Final</dt><dd>{o.final_tests ? `${o.final_tests.outcome} ${o.final_tests.passed}/${o.final_tests.total}` : "—"}</dd></div>
        <div><dt className="text-fg3">Repair cycles</dt><dd>{o.repair_cycles}</dd></div><div><dt className="text-fg3">Tokens</dt><dd>{o.tokens_used.toLocaleString()}</dd></div></dl>
      {a && (
        <div className="rounded-lg border border-line bg-surface p-3 text-sm">
          <h4 className="mb-1 text-xs font-semibold">What happened to your repository</h4>
          {a.error ? <p className="text-danger">{a.error}</p> : a.branch ? (
            <ul className="space-y-0.5 text-xs text-fg2"><li>Branch <Mono>{a.branch}</Mono> created from <Mono>{a.base_branch}</Mono>, commit <Mono>{a.commit?.slice(0, 10)}</Mono></li>
              <li>{a.pushed ? "Pushed to GitHub." : "Not pushed (local clone only)."}{a.push_error && <span className="text-warning"> {a.push_error}</span>}</li>
              {a.pr_url && <li><a className="inline-flex items-center gap-1 text-accent underline" href={a.pr_url} target="_blank" rel="noreferrer">Pull request<ExternalLink className="h-3 w-3" /></a></li>}</ul>
          ) : <p className="text-xs text-fg2">Patch applied to <Mono>{a.applied_to}</Mono>.</p>}
          {d.status === "COMPLETED" && d.repository?.source_type === "LOCAL_PATH" && <Button size="sm" className="mt-2" onClick={async () => { try { await api.missions.rollback(d.id); setRb("Rolled back: your files are restored."); onChanged(); } catch (e) { setRb((e as Error).message); } }}><RotateCcw className="h-3.5 w-3.5" />Roll back</Button>}
          {rb && <p role="status" className="mt-1 text-xs text-fg2">{rb}</p>}
        </div>)}
      <div className="grid gap-3 lg:grid-cols-2">
        <Col title="Verified" items={o.verified} tone="success" empty="Nothing verified yet." />
        <Col title="Unresolved" items={o.unresolved} tone="danger" empty="No unresolved items." />
        <Col title="Unverified agent claims" items={o.unverified_agent_claims} tone="neutral" empty="No agent self-reports." />
        <Col title="Model claims" items={o.model_claims} tone="warning" empty="No model-suspected findings." />
      </div>
      {o.notes.map((n) => <p key={n} className="rounded border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">{n}</p>)}
    </div>
  );
}
