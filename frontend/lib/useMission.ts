"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { DevEvent, Decision, Diffs, Finding, Metrics, MissionDetail, Msg, Task, TestRun, ToolCallRow, Verification } from "./types";
import { TERMINAL } from "./types";

export interface Snapshot {
  detail: MissionDetail | null; tasks: Task[]; messages: Msg[]; decisions: Decision[]; toolCalls: ToolCallRow[]; diffs: Diffs | null;
  tests: TestRun[]; findings: Finding[]; verification: Verification | null; metrics: Metrics | null; events: DevEvent[];
}
type Key = keyof Omit<Snapshot, "events">;
const EMPTY: Snapshot = { detail: null, tasks: [], messages: [], decisions: [], toolCalls: [], diffs: null, tests: [], findings: [], verification: null, metrics: null, events: [] };

const EVENT_TYPES = ("mission.created mission.status_changed mission.completed mission.failed agent.started agent.finished task.created task.delegated task.status_changed task.superseded " +
  "decision.made message.sent critique.raised critique.resolved tool.called tool.completed tool.failed file.modified test.run_started test.passed test.failed repair.initiated " +
  "finding.created finding.resolved verification.started verification.completed approval.requested approval.resolved budget.warning human.input_requested human.input_received policy.denied").split(" ");

const REFRESH: Record<string, Key[]> = {
  "mission.status_changed": ["detail"], "mission.completed": ["detail", "tasks", "tests", "findings", "verification", "diffs", "metrics"], "mission.failed": ["detail", "metrics"],
  "mission.created": ["detail"], "agent.started": ["detail"], "agent.finished": ["detail", "metrics"], "task.created": ["tasks"], "task.status_changed": ["tasks", "detail"], "task.superseded": ["tasks"],
  "decision.made": ["decisions"], "message.sent": ["messages"], "tool.completed": ["toolCalls"], "tool.failed": ["toolCalls"], "policy.denied": ["toolCalls"], "file.modified": ["diffs", "detail"],
  "test.passed": ["tests"], "test.failed": ["tests"], "finding.created": ["findings"], "finding.resolved": ["findings"], "verification.completed": ["verification", "detail"],
  "approval.requested": ["detail"], "approval.resolved": ["detail"], "human.input_requested": ["detail"], "human.input_received": ["detail"], "repair.initiated": ["tasks", "detail"],
};

/**
 * Live mission state. REST snapshots are the source of truth for panels; the SSE stream (with Last-Event-ID resume
 * handled by EventSource) drives the activity feed and tells us which snapshots to refresh. No value is invented client-side.
 */
export function useMissionLive(id: string) {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [error, setError] = useState<ApiError | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const pending = useRef<Set<Key>>(new Set());
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  const load = useCallback(async (keys: Key[]) => {
    const fetchers: Record<Key, () => Promise<unknown>> = {
      detail: () => api.missions.get(id), tasks: () => api.missions.tasks(id), messages: () => api.missions.messages(id), decisions: () => api.missions.decisions(id),
      toolCalls: () => api.missions.toolCalls(id), diffs: () => api.missions.diffs(id), tests: () => api.missions.testRuns(id), findings: () => api.missions.findings(id),
      verification: () => api.missions.verification(id), metrics: () => api.missions.metrics(id),
    };
    const results = await Promise.allSettled(keys.map((k) => fetchers[k]()));
    if (!alive.current) return;
    setSnap((s) => {
      const next = { ...s } as Record<string, unknown>;
      results.forEach((r, i) => { if (r.status === "fulfilled") next[keys[i]] = r.value; });
      return next as unknown as Snapshot;
    });
    const failed = results.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    if (failed && keys.includes("detail")) setError(failed.reason as ApiError); else if (keys.includes("detail")) setError(null);
  }, [id]);

  const schedule = useCallback((keys: Key[]) => {
    keys.forEach((k) => pending.current.add(k));
    if (timer.current) return;
    timer.current = setTimeout(() => {
      timer.current = null;
      const ks = Array.from(pending.current);
      pending.current.clear();
      void load(ks);
    }, 250);
  }, [load]);

  useEffect(() => {
    alive.current = true;
    const all: Key[] = ["detail", "tasks", "messages", "decisions", "toolCalls", "diffs", "tests", "findings", "verification", "metrics"];
    const t0 = setTimeout(() => { void load(all).finally(() => alive.current && setLoading(false)); }, 0); // initial snapshot (async: never setState in the effect body)
    const es = new EventSource(api.missions.eventsUrl(id));
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    const seen = new Set<string>();
    const handler = (type: string) => (ev: MessageEvent) => {
      if (seen.has(ev.lastEventId)) return; // idempotent: duplicate delivery changes nothing
      seen.add(ev.lastEventId);
      let data: Record<string, unknown> = {};
      try { data = JSON.parse(ev.data); } catch { /* ignore malformed */ }
      const { mission_id: _m, ts, actor, task_id, ...payload } = data as { mission_id?: string; ts?: string; actor?: string; task_id?: string | null } & Record<string, unknown>;
      void _m;
      const e: DevEvent = { id: ev.lastEventId, type, actor: actor ?? "system", task_id: task_id ?? null, created_at: ts ?? new Date().toISOString(), payload };
      setSnap((s) => ({ ...s, events: [...s.events, e].slice(-1500) }));
      schedule(REFRESH[type] ?? []);
      if (type.startsWith("test.")) schedule(["metrics"]);
    };
    EVENT_TYPES.forEach((t) => es.addEventListener(t, handler(t) as EventListener));
    return () => { alive.current = false; clearTimeout(t0); es.close(); if (timer.current) { clearTimeout(timer.current); timer.current = null; } };
  }, [id, load, schedule]);

  const refresh = useCallback(() => load(["detail", "tasks", "diffs", "tests", "findings", "verification", "metrics"]), [load]);
  const terminal = snap.detail ? TERMINAL.includes(snap.detail.status) : false;
  return { ...snap, error, connected, loading, refresh, terminal };
}
