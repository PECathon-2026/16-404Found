import type { DevEvent, Finding, MissionDetail, MissionSummary, Task, TestRun, Verification } from "./types";

export type StageState = "completed" | "active" | "pending" | "failed" | "blocked";
export interface Stage { id: string; label: string; state: StageState; evidence: { label: string; id?: string }[] }
const DEV = new Set(["IMPLEMENT", "WRITE_TESTS", "REPAIR"]);
const OPEN = new Set(["OPEN", "DISPUTED", "FIX_PROPOSED"]);

/** The 7 workflow stages, computed only from persisted mission state (never from animation or guesses). */
export function deriveStages(d: MissionDetail | null, tasks: Task[], tests: TestRun[], findings: Finding[], ver: Verification | null, events: DevEvent[]): Stage[] {
  const S = d?.status;
  const dead = S === "FAILED" || S === "CANCELLED" || S === "REJECTED";
  const live = (id: string) => d?.agents.find((a) => a.agent_id === id)?.status === "thinking";
  const dev = tasks.filter((t) => DEV.has(t.kind) && t.status !== "SUPERSEDED");
  const sha = d?.current_patch_sha256;
  const finalRuns = tests.filter((t) => t.kind === "TEST" && t.patch_sha256 === sha);
  const lastRun = finalRuns[finalRuns.length - 1];
  const plannerTools = events.filter((e) => e.actor === "planner" && e.type === "tool.completed");
  const openBlockers = findings.filter((f) => OPEN.has(f.status) && (f.severity === "HIGH" || f.severity === "CRITICAL"));
  const hasPlan = (d?.acceptance_criteria.length ?? 0) > 0 && tasks.length > 0;

  const stages: Stage[] = [
    { id: "analyze", label: "Analyze requirements", state: hasPlan || (d?.acceptance_criteria.length ?? 0) > 0 ? "completed" : live("planner") || S === "PLANNING" ? "active" : "pending",
      evidence: (d?.acceptance_criteria ?? []).map((c) => ({ label: `${c.id}: ${c.text}` })) },
    { id: "explore", label: "Explore repository", state: plannerTools.length > 0 ? "completed" : live("planner") ? "active" : "pending",
      evidence: plannerTools.slice(0, 6).map((e) => ({ label: `${String(e.payload.tool)} ${String(e.payload.args_summary ?? "").slice(0, 60)}`, id: String(e.payload.tool_call_id) })) },
    { id: "plan", label: "Plan implementation", state: hasPlan ? "completed" : S === "AWAITING_HUMAN" && !hasPlan ? "blocked" : S === "PLANNING" ? "active" : "pending",
      evidence: tasks.filter((t) => t.status !== "SUPERSEDED").map((t) => ({ label: `${t.key} ${t.kind}: ${t.title}`, id: t.id })) },
    { id: "implement", label: "Implement changes",
      state: dev.length === 0 ? "pending" : dev.every((t) => t.status === "DONE") ? "completed" : dev.some((t) => t.status === "FAILED") && !dev.some((t) => ["READY", "IN_PROGRESS", "IN_REVIEW"].includes(t.status)) ? "failed"
        : dev.some((t) => ["READY", "IN_PROGRESS", "IN_REVIEW", "PENDING"].includes(t.status)) ? "active" : "pending",
      evidence: dev.map((t) => ({ label: `${t.key} ${t.status}${t.retries > 1 ? ` · attempt ${t.retries}` : ""}`, id: t.id })) },
    { id: "test", label: "Run tests", state: !lastRun ? (live("tester") ? "active" : "pending") : lastRun.outcome === "GREEN" || lastRun.outcome === "NO_TESTS" ? "completed" : lastRun.outcome === "UNAVAILABLE" ? "blocked" : "failed",
      evidence: tests.filter((t) => t.kind === "TEST" || t.kind === "BASELINE").map((t) => ({ label: `${t.kind} ${t.outcome} ${t.passed}/${t.total}`, id: t.id })) },
    { id: "verify", label: "Review & verify",
      state: ver && ver.patch_sha256 === sha ? (ver.overall === "FAIL" ? "failed" : openBlockers.length ? "blocked" : ver.overall === "PASS" ? "completed" : "active")
        : openBlockers.length ? "blocked" : S === "VERIFYING" || live("verifier") || live("security") ? "active" : "pending",
      evidence: [...openBlockers.map((f) => ({ label: `OPEN ${f.severity} ${f.category}`, id: f.id })), ...(ver ? [{ label: `verifier ${ver.overall}`, id: ver.id }] : [])] },
    { id: "approve", label: "Human approval", state: S === "COMPLETED" ? "completed" : S === "AWAITING_APPROVAL" ? "active" : S === "REJECTED" ? "failed" : S === "AWAITING_HUMAN" && hasPlan ? "blocked" : "pending",
      evidence: S === "AWAITING_APPROVAL" ? [{ label: "waiting for your decision on the exact patch" }] : [] },
  ];
  if (dead) {
    const i = stages.findIndex((s) => s.state === "active");
    if (i >= 0) stages[i].state = "failed";
    else { const j = stages.findIndex((s) => s.state === "pending"); if (j >= 0 && S !== "REJECTED") stages[j].state = "failed"; }
  }
  return stages;
}

export interface Metrics4 {
  total: number; successful: number; successRate: number | null; avgMs: number | null; thisWeek: number; perDay: number[] | null;
  activeAgents: number | null;
}
export function missionMetrics(ms: MissionSummary[], activeAgents: number | null, now: number): Metrics4 {
  const done = ms.filter((m) => m.status === "COMPLETED");
  const finished = ms.filter((m) => ["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(m.status));
  const durs = done.map((m) => new Date(m.updated_at).getTime() - new Date(m.created_at).getTime()).filter((x) => x > 0);
  const week = now - 7 * 86400_000;
  const days = Array.from({ length: 7 }, (_, i) => ms.filter((m) => { const t = new Date(m.created_at).getTime(); const s = now - (6 - i) * 86400_000; return t >= s - (s % 86400_000) && t < s - (s % 86400_000) + 86400_000; }).length);
  return {
    total: ms.length, successful: done.length, successRate: finished.length ? Math.round((100 * done.length) / finished.length) : null,
    avgMs: durs.length ? Math.round(durs.reduce((a, b) => a + b, 0) / durs.length) : null,
    thisWeek: now ? ms.filter((m) => new Date(m.created_at).getTime() >= week).length : 0,
    perDay: ms.length >= 3 && now ? days : null, // a sparkline needs history; with fewer than 3 missions we show none rather than invent a trend
    activeAgents,
  };
}
export const fmtDuration = (ms: number | null) => { if (ms == null) return "no data"; const s = Math.round(ms / 1000); return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`; };
export const isActive = (s: string) => ["CREATED", "PLANNING", "EXECUTING", "VERIFYING", "AWAITING_HUMAN", "AWAITING_APPROVAL", "PAUSED"].includes(s);
