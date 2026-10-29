"use client";
import { AlertTriangle, CheckCircle2, FileCode2, FlaskConical, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import React, { useState } from "react";
import { Badge, Button, EmptyState, Mono, Modal, Skeleton, cx, textareaCls } from "@/components/ui";
import { api } from "@/lib/api";
import { shortId, shortSha } from "@/lib/format";
import type { Diffs, Finding, TestRun, Verification } from "@/lib/types";
import { SEV_TONE } from "../missions/status";

// ------------------------------------------------------------------ CodeDiffViewer (real unified diffs from git)
export function DiffPanel({ missionId, diffs, loading }: { missionId: string; diffs: Diffs | null; loading: boolean }) {
  const [sel, setSel] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  if (loading && !diffs) return <Skeleton className="m-4 h-40" />;
  if (!diffs || diffs.files.length === 0) return <EmptyState icon={<FileCode2 className="h-6 w-6" />} title="No changes yet" description="Edits made by the developer agent appear here as a real git diff of the isolated workspace." />;
  const f = diffs.files.find((x) => x.path === sel) ?? diffs.files[0];
  return (
    <div className="grid min-h-[320px] md:grid-cols-[240px_1fr]">
      <ul aria-label="Changed files" className="border-b border-line md:border-b-0 md:border-r">
        <li className="px-3 py-2 text-[11px] text-fg3">patch <Mono>{shortSha(diffs.patch_sha256)}</Mono></li>
        {diffs.files.map((x) => (
          <li key={x.path}><button onClick={() => setSel(x.path)} aria-current={x.path === f.path} className={cx("flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-hover", x.path === f.path && "bg-hover")}>
            <Badge tone={x.change_type === "ADD" ? "success" : x.change_type === "DELETE" ? "danger" : "neutral"}>{x.change_type[0]}</Badge>
            <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{x.path}</span><span className="text-[11px] text-success">+{x.additions}</span><span className="text-[11px] text-danger">−{x.deletions}</span></button></li>))}
      </ul>
      <div className="min-w-0">
        {f.tamper_flags.length > 0 && <div role="alert" className="flex items-center gap-2 border-b border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger"><ShieldX className="h-4 w-4" aria-hidden />Existing test file changed ({f.tamper_flags.join(", ")}). This blocks approval unless a human waives it.</div>}
        <div className="flex items-center gap-2 border-b border-line px-3 py-1.5"><Mono className="flex-1 truncate">{f.path}</Mono>{f.is_test_file && <Badge>test file</Badge>}
          <Button size="sm" variant="ghost" onClick={() => setFull(!full)}>{full ? "Show diff" : "Show full file"}</Button>
          <a className="text-xs text-accent underline" href={api.missions.patchUrl(missionId)} target="_blank" rel="noreferrer">patch</a></div>
        {full ? <pre className="max-h-[520px] overflow-auto p-3 font-mono text-[12px] leading-5">{(f.modified ?? "(deleted)").split("\n").map((l, i) => <div key={i}><span className="mr-3 inline-block w-8 select-none text-right text-fg3">{i + 1}</span>{l}</div>)}</pre> : <Unified text={f.unified} />}
      </div>
    </div>
  );
}

type Row = { kind: "hunk" | "add" | "del" | "ctx"; old: number | ""; neu: number | ""; text: string };
function parseUnified(text: string): Row[] {
  const rows: Row[] = [];
  let o = 0, n = 0;
  for (const l of text.split("\n")) {
    if (/^(diff |index |--- |\+\+\+ |new file|deleted file)/.test(l)) continue;
    const h = /^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(l);
    if (h) { o = +h[1]; n = +h[2]; rows.push({ kind: "hunk", old: "", neu: "", text: l }); continue; }
    if (l.startsWith("+")) rows.push({ kind: "add", old: "", neu: n++, text: l });
    else if (l.startsWith("-")) rows.push({ kind: "del", old: o++, neu: "", text: l });
    else rows.push({ kind: "ctx", old: o++, neu: n++, text: l });
  }
  return rows;
}

function Unified({ text }: { text: string }) {
  if (!text.trim()) return <p className="p-4 text-sm text-fg3">No textual diff.</p>;
  const rows = parseUnified(text);
  return (
    <pre className="max-h-[520px] overflow-auto py-2 font-mono text-[12px] leading-5">
      {rows.map((r, i) => r.kind === "hunk" ? <div key={i} className="bg-accent/10 px-3 text-accent">{r.text}</div> : (
        <div key={i} className={cx("flex px-3", r.kind === "add" && "bg-[var(--diff-add)]", r.kind === "del" && "bg-[var(--diff-del)]")}>
          <span className="w-9 shrink-0 select-none pr-2 text-right text-fg3">{r.old}</span><span className="w-9 shrink-0 select-none pr-2 text-right text-fg3">{r.neu}</span>
          <span className={cx("whitespace-pre-wrap break-all", r.kind === "add" && "text-success", r.kind === "del" && "text-danger")}>{r.text || " "}</span></div>))}
    </pre>
  );
}

// ------------------------------------------------------------------ TestResultPanel
const OUT_TONE: Record<string, "success" | "danger" | "warning" | "neutral"> = { GREEN: "success", RED: "danger", ERROR: "danger", UNAVAILABLE: "warning", NO_TESTS: "neutral" };
export function TestsPanel({ runs, loading }: { runs: TestRun[]; loading: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  if (loading && runs.length === 0) return <Skeleton className="m-4 h-32" />;
  if (runs.length === 0) return <EmptyState icon={<FlaskConical className="h-6 w-6" />} title="No test runs yet" description="The baseline run is captured before any edit; every later run is tied to the exact patch it tested." />;
  const baseline = runs.find((r) => r.kind === "BASELINE");
  return (
    <div className="divide-y divide-line">
      {runs.map((r, idx) => {
        const o = open === r.id || (open === null && idx === runs.length - 1 && r.failures.length > 0);
        const regress = baseline && r.kind === "TEST" ? r.failures.filter((f) => !baseline.failures.some((b) => b.test_id === f.test_id)) : [];
        return (
          <div key={r.id} className="px-4 py-3">
            <button className="flex w-full flex-wrap items-center gap-2 text-left" onClick={() => setOpen(o ? "" : r.id)} aria-expanded={o}>
              <Badge tone={OUT_TONE[r.outcome] ?? "neutral"} icon={r.outcome === "GREEN" ? <CheckCircle2 className="h-3 w-3" /> : r.outcome === "UNAVAILABLE" ? <AlertTriangle className="h-3 w-3" /> : r.outcome === "RED" || r.outcome === "ERROR" ? <XCircle className="h-3 w-3" /> : undefined}>{r.outcome === "UNAVAILABLE" ? "NOT EXECUTED" : r.outcome}</Badge>
              <Badge>{r.kind}</Badge><Mono>{r.runner} · {r.command}</Mono>
              <span className="text-xs text-fg3">{r.total ? `${r.passed}/${r.total} passed` : "—"}{r.failed ? ` · ${r.failed} failed` : ""}{r.errored ? ` · ${r.errored} errors` : ""} · {r.duration_s}s</span>
              <span className="ml-auto text-[11px] text-fg3">patch <Mono>{shortSha(r.patch_sha256)}</Mono> · <Mono>{shortId(r.id)}</Mono></span></button>
            {r.kind === "SELF_CHECK" && <p className="mt-1 text-[11px] text-fg3">Developer self-check: shown for transparency, never used as gate evidence.</p>}
            {regress.length > 0 && <p className="mt-1 text-xs text-danger">{regress.length} regression(s) vs baseline: {regress.map((f) => f.test_id.split("::").pop()).join(", ")}</p>}
            {o && r.failures.length > 0 && (
              <ul className="mt-2 space-y-2">{r.failures.map((f, i) => (
                <li key={i} className="rounded-md border border-line bg-canvas p-2.5"><div className="flex flex-wrap items-center gap-2"><Mono className="font-semibold">{f.test_id}</Mono><Badge tone="danger">{f.class}</Badge>
                  {baseline && !baseline.failures.some((b) => b.test_id === f.test_id) && r.kind !== "BASELINE" ? <Badge tone="danger">caused by patch</Badge> : r.kind !== "BASELINE" ? <Badge>pre-existing</Badge> : null}</div>
                  <p className="mt-1 whitespace-pre-wrap text-xs text-fg2">{f.message}</p>
                  {f.suspected_files?.length ? <p className="mt-1 text-xs text-fg3">suspects: {f.suspected_files.map((s) => <Mono key={s} className="mr-2">{s}</Mono>)}</p> : null}</li>))}</ul>)}
          </div>);
      })}
    </div>
  );
}

// ------------------------------------------------------------------ SecurityFindingCard list
export function SecurityPanel({ missionId, findings, loading, onChanged }: { missionId: string; findings: Finding[]; loading: boolean; onChanged: () => void }) {
  const [waive, setWaive] = useState<Finding | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (loading && findings.length === 0) return <Skeleton className="m-4 h-32" />;
  if (findings.length === 0) return <EmptyState icon={<ShieldCheck className="h-6 w-6" />} title="No findings" description="Secret, injection and unsafe-operation scans run on every patch. Findings appear here with file, line and evidence." />;
  const rank = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"];
  const sorted = [...findings].sort((a, b) => rank.indexOf(a.severity) - rank.indexOf(b.severity));
  async function doWaive() {
    if (!waive) return;
    setBusy(true); setErr(null);
    try { await api.missions.waive(missionId, waive.id, reason); setWaive(null); setReason(""); onChanged(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <>
      <ul className="divide-y divide-line">{sorted.map((f) => {
        const open = ["OPEN", "DISPUTED", "FIX_PROPOSED"].includes(f.status);
        return (
          <li key={f.id} className="space-y-1.5 px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={SEV_TONE[f.severity]} icon={f.severity === "CRITICAL" || f.severity === "HIGH" ? <ShieldX className="h-3 w-3" /> : undefined}>{f.severity}</Badge>
              <span className="text-sm font-medium">{f.category.replaceAll("_", " ")}</span>{f.cwe && <Badge>{f.cwe}</Badge>}
              <Badge tone={open ? "warning" : f.status === "RESOLVED" ? "success" : "neutral"}>{f.status}</Badge>
              <Badge title="how this was found">{f.source.startsWith("scanner") ? (f.source.includes("pre_existing") ? "scanner · untouched file" : "scanner-confirmed") : "model-suspected"}</Badge>
              <span className="ml-auto text-[11px] text-fg3">confidence {Math.round(f.confidence * 100)}%</span></div>
            <p className="text-xs text-fg3"><Mono>{f.file ?? "—"}{f.line_start ? `:${f.line_start}` : ""}</Mono> · raised by {f.raised_by}</p>
            {f.evidence && <pre className="overflow-x-auto rounded border border-line bg-canvas px-2.5 py-1.5 font-mono text-[12px] text-fg2">{f.evidence}</pre>}
            <p className="text-sm text-fg2"><b>Fix:</b> {f.recommendation}</p>
            {f.waive_reason && <p className="text-xs text-warning">Waived by a human: {f.waive_reason}</p>}
            {open && (f.severity === "HIGH" || f.severity === "CRITICAL" || f.severity === "MEDIUM") && <Button size="sm" variant="ghost" onClick={() => setWaive(f)}>Waive with reason…</Button>}
          </li>);
      })}</ul>
      <Modal open={!!waive} onClose={() => setWaive(null)} title="Waive this finding">
        <p className="mb-2 text-sm text-fg2">A waived {waive?.severity} finding stops blocking approval. Your reason is recorded in the report.</p>
        <textarea className={textareaCls} rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why is this acceptable?" />
        {err && <p role="alert" className="mt-2 text-sm text-danger">{err}</p>}
        <div className="mt-3 flex justify-end gap-2"><Button variant="ghost" onClick={() => setWaive(null)}>Cancel</Button><Button variant="danger" onClick={doWaive} loading={busy} disabled={reason.trim().length < 3}>Waive finding</Button></div>
      </Modal>
    </>
  );
}

export function VerificationSummary({ v }: { v: Verification | null }) {
  if (!v) return <p className="text-xs text-fg3">No independent verification yet.</p>;
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2"><Badge tone={v.overall === "PASS" ? "success" : v.overall === "FAIL" ? "danger" : "warning"}>{v.overall}</Badge><span className="text-xs text-fg3">independent process on patch <Mono>{shortSha(v.patch_sha256)}</Mono></span></div>
      {v.regression_check?.new_failures?.length ? <p className="text-xs text-danger">New failures vs baseline: {v.regression_check.new_failures.join(", ")}</p> : <p className="text-xs text-fg3">No new failures vs. baseline{v.regression_check?.fixed?.length ? ` · fixed: ${v.regression_check.fixed.length}` : ""}.</p>}
    </div>
  );
}
