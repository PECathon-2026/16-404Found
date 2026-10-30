"use client";
import { CheckCircle2, Lock, Search, SkipForward, Terminal as TermIcon, XCircle } from "lucide-react";
import React, { useMemo, useState } from "react";
import { Badge, EmptyState, ErrorCard, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { clock } from "@/lib/format";
import type { TestRun, ToolCallRow } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { TerminalOutput } from "../workspace/ActivityFeed";
import { guild } from "./identity";

/** Read-only terminal: the commands DevPilot's agents actually ran in the sandbox, with their real (redacted) output. */
export function TerminalPanel({ missionId, toolCalls }: { missionId: string | null; toolCalls: ToolCallRow[] }) {
  const [q, setQ] = useState("");
  const [onlyProblems, setOnlyProblems] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [full, setFull] = useState<Record<string, string>>({});
  const rows = useMemo(() => toolCalls.filter((t) => ["shell.run", "check.test", "check.lint", "check.build", "git.checkpoint", "git.diff", "sec.scan_secrets", "sec.scan_patterns"].includes(t.tool) || t.status !== "OK")
    .filter((t) => (!onlyProblems || t.status !== "OK") && (!q.trim() || `${t.tool} ${JSON.stringify(t.args)} ${t.output_excerpt ?? ""}`.toLowerCase().includes(q.toLowerCase()))), [toolCalls, q, onlyProblems]);
  async function expand(t: ToolCallRow) {
    setOpen(open === t.id ? null : t.id);
    if (missionId && !(t.id in full)) { try { const r = await api.missions.toolCall(missionId, t.id); setFull((f) => ({ ...f, [t.id]: r.full_output ?? r.output_excerpt ?? "" })); } catch { setFull((f) => ({ ...f, [t.id]: t.output_excerpt ?? "" })); } }
  }
  return (
    <div className="flex h-full min-h-[240px] flex-col font-mono">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 font-sans">
        <div className="relative min-w-[150px] flex-1"><Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-fg3" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search commands and output" aria-label="Search terminal" className="h-8 w-full rounded-md border border-line bg-black/20 pl-7 pr-2 text-xs outline-none focus:border-accent" /></div>
        <label className="flex items-center gap-1.5 text-xs text-fg2"><input type="checkbox" checked={onlyProblems} onChange={(e) => setOnlyProblems(e.target.checked)} />problems only</label>
        <Badge icon={<Lock className="h-3 w-3" />} title="Commands run through the sandbox allowlist. This terminal cannot execute anything.">read-only</Badge></div>
      <div className="min-h-0 flex-1 overflow-y-auto bg-black/30 p-2 text-[12px]" role="log" aria-label="Command log">
        {!missionId ? <EmptyState title="No mission selected" /> : rows.length === 0 ? <EmptyState icon={<TermIcon className="h-6 w-6" />} title={toolCalls.length ? "No matching commands" : "No commands yet"} description="Every command an agent runs inside the sandbox appears here with its exit code and output." />
          : rows.map((t) => {
            const g = guild(t.agent_id), bad = t.status !== "OK" || (t.exit_code != null && t.exit_code !== 0);
            return (
              <div key={t.id} className="mb-1">
                <button onClick={() => void expand(t)} aria-expanded={open === t.id} className="flex w-full flex-wrap items-baseline gap-x-2 rounded px-1.5 py-1 text-left hover:bg-hover">
                  <span style={{ color: g.color }} className="font-semibold">{g.name.toLowerCase()}</span><span className="text-fg3">$</span>
                  <span className="min-w-0 flex-1 break-all text-fg">{t.tool} {Object.entries(t.args ?? {}).map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join(" ").slice(0, 140)}</span>
                  <span className={cx("shrink-0 text-[11px]", bad ? "text-danger" : "text-success")}>{t.status === "DENIED" ? "DENIED" : t.exit_code != null ? `exit ${t.exit_code}` : t.status}</span>
                  <time className="shrink-0 text-[10px] text-fg3">{clock(t.started_at)}</time></button>
                {open === t.id && <div className="ml-4"><TerminalOutput text={full[t.id] ?? t.output_excerpt ?? ""} loading={!(t.id in full)} policy={t.policy_reason} /></div>}
              </div>);
          })}
      </div>
    </div>
  );
}

export function FileView({ missionId, path }: { missionId: string | null; path: string | null }) {
  const { data, error, loading } = useApi(async () => (missionId && path ? api.missions.fileContent(missionId, path) : null), [missionId, path]);
  if (!path) return <EmptyState title="Select a file" description="Pick a file in the repository explorer to read it." />;
  if (error) return <div className="p-3"><ErrorCard message={error.message} /></div>;
  if (loading && !data) return <Skeleton className="m-3 h-40" />;
  if (data?.binary) return <p className="p-4 text-sm text-fg3">Binary file.</p>;
  return (
    <div className="flex h-full min-h-0 flex-col"><div className="border-b border-line px-3 py-1.5 font-mono text-xs text-fg2">{path}</div>
      <pre className="min-h-0 flex-1 overflow-auto p-0 py-2 font-mono text-[12px] leading-5">{(data?.content ?? "").split("\n").map((l, i) => <div key={i} className="flex px-3 hover:bg-hover"><span className="w-9 shrink-0 select-none pr-2 text-right text-fg3">{i + 1}</span><span className="whitespace-pre-wrap break-all">{l || " "}</span></div>)}</pre></div>
  );
}

/** Pass / fail / skipped and individual test results of the latest gate run. Coverage is shown as "not collected": we never invent it. */
export function TestResultsMini({ missionId, runs, onViewLogs }: { missionId: string | null; runs: TestRun[]; onViewLogs: () => void }) {
  const main = [...runs].reverse().find((r) => r.kind === "TEST") ?? [...runs].reverse().find((r) => r.kind === "BASELINE");
  const lint = [...runs].reverse().find((r) => r.kind === "LINT"), build = [...runs].reverse().find((r) => r.kind === "BUILD");
  const { data } = useApi(async () => (missionId && main ? api.missions.testCases(missionId, main.id) : null), [missionId, main?.id]);
  if (!main) return <EmptyState title="No test runs yet" description="The baseline run is captured before any edit; every later run is tied to its patch." />;
  const chip = (label: string, r: TestRun | undefined) => <Badge tone={!r ? "neutral" : r.outcome === "GREEN" ? "success" : r.outcome === "RED" ? "danger" : "warning"}>{label}: {r ? (r.outcome === "NO_TESTS" ? "n/a" : r.outcome.toLowerCase()) : "not run"}</Badge>;
  const cases = data?.available ? data.cases : (main.failures ?? []).map((f) => ({ test_id: f.test_id, status: "FAILED", duration_s: 0 }));
  return (
    <div className="space-y-2.5 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="success" icon={<CheckCircle2 className="h-3 w-3" />}>{main.passed} passed</Badge><Badge tone={main.failed + main.errored ? "danger" : "neutral"} icon={<XCircle className="h-3 w-3" />}>{main.failed + main.errored} failed</Badge>
        <Badge icon={<SkipForward className="h-3 w-3" />}>{main.skipped} skipped</Badge><span className="ml-auto text-xs text-fg3">{main.kind === "BASELINE" ? "baseline · " : ""}{main.duration_s}s</span></div>
      <ul className="max-h-44 divide-y divide-line overflow-y-auto rounded-lg border border-line bg-black/20 font-mono text-[11.5px]">
        {cases.length === 0 && <li className="px-2.5 py-2 text-fg3">{main.total ? "This runner reported totals only (no per-test list)." : "No tests executed."}</li>}
        {cases.map((c) => <li key={c.test_id} className={cx("flex items-center gap-2 px-2.5 py-1.5", c.status === "FAILED" && "text-danger")}><span className="min-w-0 flex-1 truncate">{c.test_id.replace("tests/", "")}</span>
          <span className={cx("shrink-0 text-[10px] font-semibold", c.status === "PASSED" ? "text-success" : c.status === "FAILED" ? "text-danger" : "text-fg3")}>{c.status}</span>{c.duration_s > 0 && <span className="w-9 shrink-0 text-right text-fg3">{c.duration_s.toFixed(2)}s</span>}</li>)}</ul>
      <div className="flex flex-wrap gap-1.5">{chip("lint", lint)}{chip("build", build)}<Badge title="No coverage tool is configured in the sandbox">coverage: not collected</Badge>
        <button onClick={onViewLogs} className="ml-auto rounded-md border border-line px-2 py-0.5 text-xs text-fg2 hover:bg-hover">View logs</button></div>
    </div>
  );
}
