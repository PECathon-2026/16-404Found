"use client";
import { Ban, GitBranch, Pause, Play, Wifi, WifiOff } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import React, { Suspense, useCallback, useState } from "react";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorBoundary, ErrorCard, Mono, Skeleton, Tabs, Github } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { shortId } from "@/lib/format";
import type { DevEvent, MissionDetail } from "@/lib/types";
import { useMissionLive } from "@/lib/useMission";
import { AgentCard, AgentNetworkGraph, MetricsPanel } from "../agents/agents";
import { MissionStatusBadge } from "../missions/status";
import { ActivityFeed } from "./ActivityFeed";
import { ApprovalPanel, HumanRequestCard } from "./ApprovalPanel";
import { CriteriaList, TaskDependencyGraph } from "./PlanPanel";
import { DiffPanel, SecurityPanel, TestsPanel } from "./panels";
import { ReportPanel } from "./ReportPanel";
import { ExecutionReplay, MissionTimeline } from "./Timeline";

type Tab = "activity" | "plan" | "diff" | "tests" | "security" | "network" | "timeline" | "report";

export function MissionWorkspacePage() {
  return <Suspense fallback={<div className="space-y-3 p-6"><Skeleton className="h-16" /><Skeleton className="h-64" /></div>}><Keyed /></Suspense>;
}

// Keyed by mission id so navigating between missions remounts with fresh state.
function Keyed() {
  const { missionId } = useParams<{ missionId: string }>();
  return <Workspace key={missionId} missionId={missionId} />;
}

function Workspace({ missionId }: { missionId: string }) {
  const live = useMissionLive(missionId);
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") as Tab) || "activity";
  const initialAgent = searchParams.get("agent") || null;
  const { detail: d, error } = live;
  const [tab, setTab] = useState<Tab>(initialTab);
  const [agent, setAgent] = useState<string | null>(initialAgent);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);
  const [replayEvents, setReplayEvents] = useState<DevEvent[] | null>(null);
  const [ctlErr, setCtlErr] = useState<string | null>(null);
  const onFrame = useCallback((e: DevEvent[] | null) => setReplayEvents(e), []);

  if (error && !d) return <div className="p-6"><ErrorCard title={error.status === 404 ? "Mission not found" : "Could not load the mission"} message={error.message} onRetry={() => void live.refresh()} />
    <Link href="/missions" className="mt-3 inline-block text-sm text-accent underline">Back to missions</Link></div>;
  if (!d) return <div className="space-y-3 p-6"><Skeleton className="h-16" /><Skeleton className="h-64" /></div>;

  const events = replayEvents ?? live.events;
  const act = async (fn: () => Promise<MissionDetail>) => { setCtlErr(null); try { await fn(); await live.refresh(); } catch (e) { setCtlErr((e as ApiError).message); } };
  const tasksDone = live.tasks.filter((t) => t.status === "DONE").length, tasksTotal = live.tasks.filter((t) => t.status !== "SUPERSEDED").length;
  const critPass = d.acceptance_criteria.filter((c) => c.status === "PASS").length;
  const openF = live.findings.filter((f) => ["OPEN", "DISPUTED", "FIX_PROPOSED"].includes(f.status));
  const failRuns = live.tests.filter((t) => t.kind === "TEST" && ["RED", "ERROR"].includes(t.outcome)).length;
  const active = !["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(d.status);
  const tabs: { id: Tab; label: string; badge?: React.ReactNode }[] = [
    { id: "activity", label: "Activity", badge: <Badge>{events.length}</Badge> }, { id: "plan", label: "Plan", badge: tasksTotal ? <Badge>{tasksDone}/{tasksTotal}</Badge> : null },
    { id: "diff", label: "Diff", badge: live.diffs?.files.length ? <Badge>{live.diffs.files.length}</Badge> : null }, { id: "tests", label: "Tests", badge: failRuns ? <Badge tone="danger">{failRuns} red</Badge> : null },
    { id: "security", label: "Security", badge: openF.length ? <Badge tone="warning">{openF.length} open</Badge> : null }, { id: "network", label: "Network" },
    { id: "timeline", label: "Timeline" }, { id: "report", label: "Report" },
  ];

  return (
    <div className="flex flex-col">
      {/* ---- MissionHeader */}
      <div className="min-w-0 border-b border-line bg-canvas px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="min-w-0 truncate text-lg font-semibold">{d.title}</h1><MissionStatusBadge status={d.status} reason={d.status_reason} />
          {d.mode === "scripted" && <Badge title="The model is a scripted replay. Tools, tests, verifier, scans and the gate are real.">demo model</Badge>}
          <Badge
            tone={d.sandbox_mode === "container_isolated" || d.sandbox_mode === "docker_jail" ? "success" : "warning"}
            title={d.sandbox_mode === "container_isolated" || d.sandbox_mode === "docker_jail" ? "Container-isolated sandbox: running in isolated non-root container with path jail" : "Local-jail sandbox: not a container"}
          >
            sandbox: {d.sandbox_mode?.replace("_", "-") ?? "container-isolated"}
          </Badge>
          <span className={`ml-auto inline-flex items-center gap-1 text-xs ${live.connected ? "text-success" : "text-warning"}`} role="status">{live.connected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}{replayEvents ? "Replay" : live.connected ? "Live" : "Reconnecting…"}</span>
          {active && <div className="flex gap-1.5">
            {d.status === "PAUSED" ? <Button size="sm" onClick={() => act(() => api.missions.resume(d.id))}><Play className="h-3.5 w-3.5" />Resume</Button>
              : ["PLANNING", "EXECUTING", "VERIFYING", "CREATED"].includes(d.status) && <Button size="sm" onClick={() => act(() => api.missions.pause(d.id))}><Pause className="h-3.5 w-3.5" />Pause</Button>}
            <Button size="sm" variant="danger" onClick={() => { if (confirm("Cancel this mission? Evidence is kept; your repository is not changed.")) void act(() => api.missions.cancel(d.id)); }}><Ban className="h-3.5 w-3.5" />Cancel</Button></div>}
        </div>
        <p className="mt-1 line-clamp-2 max-w-4xl text-sm text-fg2">{d.request}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg3">
          <span className="inline-flex items-center gap-1">{d.repository?.source_type === "GIT_URL" ? <Github className="h-3.5 w-3.5" /> : <GitBranch className="h-3.5 w-3.5" />}{d.repository?.github_owner ? `${d.repository.github_owner}/${d.repository.github_name}` : d.repository?.name}{d.base_commit && <Mono>@{d.base_commit.slice(0, 7)}</Mono>}</span>
          <span>tasks {tasksDone}/{tasksTotal || "—"}</span><span>criteria {critPass}/{d.acceptance_criteria.length || "—"} verified</span><span>repair cycles {d.counters.repair_cycles}</span><Mono title={d.id}>{shortId(d.id)}</Mono>
        </div>
        {tasksTotal > 0 && <div className="mt-2 h-1 overflow-hidden rounded bg-hover" role="progressbar" aria-label={`${tasksDone} of ${tasksTotal} tasks done`} aria-valuenow={tasksDone} aria-valuemax={tasksTotal}><div className="h-full bg-success transition-all" style={{ width: `${(100 * tasksDone) / tasksTotal}%` }} /></div>}
        {ctlErr && <p role="alert" className="mt-2 text-sm text-danger">{ctlErr}</p>}
      </div>

      <div className="grid min-w-0 gap-4 p-4 sm:p-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="order-2 min-w-0 space-y-4 xl:order-1">
          {replayEvents && <p className="rounded border border-warning/30 bg-warning/10 px-3 py-1.5 text-xs text-warning">Replay mode: the feed shows persisted events up to the scrubber, not live activity.</p>}
          <Card><Tabs label="Mission views" tabs={tabs} value={tab} onChange={setTab} />
            <ErrorBoundary label="This view">
              {tab === "activity" && <ActivityFeed missionId={d.id} events={events} messages={live.messages} toolCalls={live.toolCalls} loading={live.loading} filterAgent={agent} onFilterAgent={setAgent} />}
              {tab === "plan" && <div><CardHeader title="Acceptance criteria" sub={`version ${d.criteria_version}`} /><CriteriaList criteria={d.acceptance_criteria} objectives={d.objectives} />
                <div className="border-t border-line">
                  <TaskDependencyGraph
                    tasks={live.tasks}
                    selected={selectedTask}
                    onSelect={(t) => setSelectedTask(t.id === selectedTask ? null : t.id)}
                    onFilterAgent={(a) => { setAgent(a); setTab("activity"); }}
                  />
                </div>
                {d.risks.length > 0 && <div className="border-t border-line px-4 py-3"><h4 className="text-xs font-semibold text-fg3">Risks noted by the planner</h4><ul className="mt-1 list-disc pl-5 text-sm text-fg2">{d.risks.map((r) => <li key={r}>{r}</li>)}</ul></div>}</div>}
              {tab === "diff" && <DiffPanel missionId={d.id} diffs={live.diffs} loading={live.loading} />}
              {tab === "tests" && <TestsPanel runs={live.tests} loading={live.loading} />}
              {tab === "security" && <SecurityPanel missionId={d.id} findings={live.findings} loading={live.loading} onChanged={() => void live.refresh()} />}
              {tab === "network" && (
                <AgentNetworkGraph
                  detail={d}
                  messages={live.messages}
                  events={events}
                  selectedAgent={agent}
                  onSelectAgent={(a) => { setAgent(a); setTab("activity"); }}
                />
              )}
              {tab === "timeline" && <div><MissionTimeline events={events} />{!active && <div className="border-t border-line p-4"><ExecutionReplay missionId={d.id} onFrame={onFrame} /></div>}</div>}
              {tab === "report" && <ReportPanel d={d} onChanged={() => void live.refresh()} />}
            </ErrorBoundary></Card>
        </div>

        <aside className="order-1 min-w-0 space-y-4 xl:order-2" aria-label="Mission side panel">
          {d.status === "AWAITING_HUMAN" && d.pending_human_request && <HumanRequestCard key={d.pending_human_request.id} missionId={d.id} req={d.pending_human_request} onDone={() => void live.refresh()} />}
          {d.status === "AWAITING_APPROVAL" && <ApprovalPanel key={d.current_patch_sha256 ?? "x"} d={d} diffs={live.diffs} tests={live.tests} findings={live.findings} verification={live.verification} onDone={() => void live.refresh()} />}
          {["COMPLETED", "REJECTED", "FAILED", "CANCELLED"].includes(d.status) && (
            <Card className={d.status === "COMPLETED" ? "border-success/40" : "border-danger/40"}><div className="space-y-1 p-4"><MissionStatusBadge status={d.status} /><p className="text-sm text-fg2">{d.status_reason}</p>
              <button className="text-sm text-accent underline" onClick={() => setTab("report")}>Open the evidence report</button></div></Card>)}
          <Card><CardHeader title="Agents" sub="click to filter the activity feed" /><div className="space-y-1.5 p-3">
            {d.agents.map((a) => <AgentCard key={a.agent_id} a={a} active={agent === a.agent_id} onClick={() => { setAgent(agent === a.agent_id ? null : a.agent_id); setTab("activity"); }} />)}</div></Card>
          <MetricsPanel m={live.metrics} d={d} />
          {live.messages.length === 0 && live.loading && <Skeleton className="h-10" />}
          {!live.loading && d.acceptance_criteria.length === 0 && d.status !== "FAILED" && <EmptyState title="Planning…" description="The Architect is inspecting the repository before it writes a plan." />}
        </aside>
      </div>
    </div>
  );
}
