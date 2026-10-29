"use client";
import { CheckCircle2, ChevronDown, ChevronRight, ClipboardCheck, Play, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorCard, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function Page() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi(() => api.evalResults(), []);
  const { data: sc } = useApi(() => api.demo.scenarios(), []);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const res = data?.results ?? null;
  const passed = res?.filter((r) => r.ok).length ?? 0;
  const runnable = new Set((sc?.scenarios ?? []).map((s) => s.id));

  async function run(id: string) {
    setBusy(id);
    try { const m = await api.demo.create(id); router.push(`/missions/${m.id}`); } finally { setBusy(null); }
  }
  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div><h1 className="text-xl font-semibold">Evaluation</h1>
        <p className="text-sm text-fg3">The PS-001 scenarios, run end to end. Every check is computed from persisted events, test runs, findings and tool calls, never from agent text.</p></div>
      <div className="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-fg2">These runs use a <b>scripted model</b>. Tools, tests, scanners, the independent verifier, the completion gate and approval are real. Re-run them from the backend with <code className="font-mono">python -m app.evalkit</code>.</div>
      {error ? <ErrorCard message={error.message} onRetry={reload} /> : loading ? <Skeleton className="h-48" /> : !res ? (
        <Card><EmptyState icon={<ClipboardCheck className="h-6 w-6" />} title="No evaluation results yet" description={data?.note ?? "Run python -m app.evalkit in backend/."} /></Card>
      ) : (
        <>
          <div className="flex items-center gap-3"><Badge tone={passed === res.length ? "success" : "danger"}>{passed}/{res.length} scenarios passed</Badge>
            <span className="text-xs text-fg3">{res.reduce((a, r) => a + r.checks.filter((c) => c.ok).length, 0)} of {res.reduce((a, r) => a + r.checks.length, 0)} checks</span></div>
          <Card><ul className="divide-y divide-line">{res.map((r) => (
            <li key={r.id}>
              <div className="flex items-center gap-3 px-4 py-3">
                <button className="flex min-w-0 flex-1 items-center gap-3 text-left" onClick={() => setOpen(open === r.id ? null : r.id)} aria-expanded={open === r.id}>
                  {open === r.id ? <ChevronDown className="h-4 w-4 shrink-0 text-fg3" /> : <ChevronRight className="h-4 w-4 shrink-0 text-fg3" />}
                  {r.ok ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-label="passed" /> : <XCircle className="h-4 w-4 shrink-0 text-danger" aria-label="failed" />}
                  <span className="min-w-0"><span className="block truncate text-sm font-medium">{r.title}</span><span className="block truncate font-mono text-[11px] text-fg3">{r.id}</span></span></button>
                <Badge tone={r.ok ? "success" : "danger"}>{r.checks.filter((c) => c.ok).length}/{r.checks.length}</Badge><Badge>{r.final_status}</Badge>
                {runnable.has(r.id) && <Button size="sm" onClick={() => run(r.id)} loading={busy === r.id}><Play className="h-3.5 w-3.5" aria-hidden />Run live</Button>}
              </div>
              {open === r.id && <ul className="space-y-1 border-t border-line bg-canvas px-4 py-3">{r.checks.map((c) => (
                <li key={c.name} className="flex items-start gap-2 text-sm">{c.ok ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-label="pass" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-label="fail" />}
                  <span className="text-fg2">{c.name}{c.detail && !c.ok ? <span className="text-danger"> ({c.detail})</span> : null}</span></li>))}</ul>}
            </li>))}</ul></Card>
        </>)}
    </div>
  );
}
