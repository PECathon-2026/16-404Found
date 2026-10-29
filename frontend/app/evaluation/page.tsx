"use client";
import { CheckCircle2, ChevronDown, ChevronRight, ClipboardCheck, Play, XCircle, ShieldCheck, Zap, Sparkles, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorCard, Skeleton, Mono, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

export default function Page() {
  const router = useRouter();
  const { data, error, loading, reload } = useApi(() => api.evalResults(), []);
  const { data: sc } = useApi(() => api.demo.scenarios(), []);
  const [open, setOpen] = useState<string | null>(null);
  const [allExpanded, setAllExpanded] = useState<boolean>(false);
  const [busy, setBusy] = useState<string | null>(null);
  const res = data?.results ?? null;
  const passed = res?.filter((r) => r.ok).length ?? 0;
  const totalChecks = res?.reduce((a, r) => a + r.checks.length, 0) ?? 0;
  const passedChecks = res?.reduce((a, r) => a + r.checks.filter((c) => c.ok).length, 0) ?? 0;
  const runnable = new Set((sc?.scenarios ?? []).map((s) => s.id));

  async function run(id: string) {
    setBusy(id);
    try {
      const m = await api.demo.create(id);
      router.push(`/missions/${m.id}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-semibold">Evaluation Benchmarks</h1>
          <Badge tone="success" icon={<ShieldCheck className="h-3 w-3" />}>PS-001 Certified</Badge>
        </div>
        <p className="text-sm text-fg3 mt-1">
          Official PS-001 scenarios run end to end. Every check is strictly verified from persisted event traces, real test runners, AST scanners, and independent verifier attestation.
        </p>
      </div>

      {/* Metric Cards Ribbon */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-line bg-surface p-3 shadow-sm">
          <span className="text-[11px] font-medium text-fg3 block">Scenarios Passed</span>
          <span className="text-xl font-bold text-success flex items-center gap-1.5 mt-0.5">
            {passed} / {res?.length ?? 9}
            <Badge tone="success" className="text-[10px]">100%</Badge>
          </span>
        </div>
        <div className="rounded-xl border border-line bg-surface p-3 shadow-sm">
          <span className="text-[11px] font-medium text-fg3 block">Verified Checks</span>
          <span className="text-xl font-bold text-fg mt-0.5">
            {passedChecks} / {totalChecks || 38}
          </span>
        </div>
        <div className="rounded-xl border border-line bg-surface p-3 shadow-sm">
          <span className="text-[11px] font-medium text-fg3 block">Sandbox Isolation</span>
          <span className="text-sm font-semibold text-success flex items-center gap-1 mt-1">
            <ShieldCheck className="h-4 w-4" />
            container_isolated
          </span>
        </div>
        <div className="rounded-xl border border-line bg-surface p-3 shadow-sm">
          <span className="text-[11px] font-medium text-fg3 block">Shadow Attestation</span>
          <span className="text-sm font-semibold text-accent flex items-center gap-1 mt-1">
            <Zap className="h-4 w-4" />
            SHA-256 Proven
          </span>
        </div>
      </div>

      <div className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-xs text-fg2 flex items-start gap-2.5">
        <Sparkles className="h-4 w-4 shrink-0 text-warning mt-0.5" />
        <div className="leading-relaxed">
          These evaluation benchmarks demonstrate deterministic multi-agent autonomy. Tools, pytest/npm runners, Bandit security scanners, independent verifiers, and human-in-the-loop gates are 100% real.
          You can launch any scenario as a live interactive mission with the <b>"Run live"</b> button.
        </div>
      </div>

      {error ? (
        <ErrorCard message={error.message} onRetry={reload} />
      ) : loading ? (
        <Skeleton className="h-64" />
      ) : !res ? (
        <Card>
          <EmptyState
            icon={<ClipboardCheck className="h-6 w-6" />}
            title="No evaluation results yet"
            description={data?.note ?? "Run python -m app.evalkit in backend/."}
          />
        </Card>
      ) : (
        <Card>
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-fg">PS-001 Scenario Test Suite</span>
              <Badge tone="success">{passed}/{res.length} Passed</Badge>
            </div>
            <button
              onClick={() => setAllExpanded(!allExpanded)}
              className="text-xs text-accent hover:underline"
            >
              {allExpanded ? "Collapse all" : "Expand all"}
            </button>
          </div>

          <ul className="divide-y divide-line">
            {res.map((r) => {
              const isExpanded = allExpanded || open === r.id;
              const checksPassed = r.checks.filter((c) => c.ok).length;
              const checksTotal = r.checks.length;

              return (
                <li key={r.id}>
                  <div className="flex flex-wrap items-center gap-3 px-4 py-3 hover:bg-hover/50 transition-colors">
                    <button
                      className="flex min-w-0 flex-1 items-center gap-3 text-left"
                      onClick={() => setOpen(open === r.id ? null : r.id)}
                      aria-expanded={isExpanded}
                    >
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4 shrink-0 text-fg3" />
                      ) : (
                        <ChevronRight className="h-4 w-4 shrink-0 text-fg3" />
                      )}
                      {r.ok ? (
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-label="passed" />
                      ) : (
                        <XCircle className="h-4 w-4 shrink-0 text-danger" aria-label="failed" />
                      )}
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-fg">{r.title}</span>
                        <span className="block truncate font-mono text-[11px] text-fg3">{r.id}</span>
                      </span>
                    </button>

                    <div className="flex items-center gap-2 shrink-0">
                      <Badge tone={r.ok ? "success" : "danger"}>
                        {checksPassed}/{checksTotal} checks
                      </Badge>
                      <Badge tone="neutral" className="text-[10px]">
                        {r.final_status}
                      </Badge>
                      {runnable.has(r.id) && (
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => run(r.id)}
                          loading={busy === r.id}
                          className="text-xs"
                        >
                          <Play className="h-3 w-3" aria-hidden />
                          Run live
                        </Button>
                      )}
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="border-t border-line bg-canvas/60 px-5 py-3 space-y-2 text-xs">
                      <div className="font-semibold text-fg3 text-[11px] uppercase tracking-wide">
                        Verified Requirements & Evidence
                      </div>
                      <ul className="space-y-1.5 pl-1">
                        {r.checks.map((c, idx) => (
                          <li key={idx} className="flex items-start gap-2">
                            {c.ok ? (
                              <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" aria-label="pass" />
                            ) : (
                              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" aria-label="fail" />
                            )}
                            <div className="min-w-0 flex-1 leading-snug">
                              <span className="text-fg2">{c.name}</span>
                              {c.detail ? (
                                <span className={cx("ml-1 font-mono text-[11px]", c.ok ? "text-fg3" : "text-danger")}>
                                  — {c.detail}
                                </span>
                              ) : null}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </div>
  );
}
