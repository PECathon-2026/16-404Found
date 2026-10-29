"use client";
import React, { useState } from "react";
import Link from "next/link";
import { ArrowRight, ExternalLink, Activity, AlertCircle, CheckCircle2, Shield, Terminal, MessageSquare, Sparkles } from "lucide-react";
import { Badge, Button, Card, CardHeader, EmptyState, Skeleton, inputCls, Mono, cx } from "@/components/ui";
import { AGENTS, AgentNetworkGraph } from "@/features/agents/agents";
import { api } from "@/lib/api";
import type { MissionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { useMissionLive } from "@/lib/useMission";

const ROLE_DETAILS: Record<string, { desc: string; tools: string[]; focus: string }> = {
  master: {
    desc: "Guild Shogun / Orchestrator. Coordinates the multi-agent graph, dispatches tasks, and evaluates state transitions.",
    tools: ["task_dispatch", "human_approval", "repair_cycle_trigger"],
    focus: "Mission lifecycle & convergence"
  },
  planner: {
    desc: "Guild Architect. Inspects the repository, defines measurable acceptance criteria, and generates deterministic task DAGs.",
    tools: ["repo_inspect", "criteria_validate", "plan_dag_generate"],
    focus: "Design, acceptance criteria & dependencies"
  },
  developer: {
    desc: "Guild Engineer (Samurai). Executes implementation tasks, generates clean code edits, and handles tool permissions.",
    tools: ["file_read", "file_write", "git_patch", "allowlist_exec"],
    focus: "Code implementation & bug fixes"
  },
  tester: {
    desc: "QA Engineer. Executes test suites, captures failure evidence, and feeds diagnostic logs back to the Architect.",
    tools: ["pytest_run", "npm_test", "evidence_capture"],
    focus: "Test verification & regression detection"
  },
  security: {
    desc: "Security Engineer (Sentinel). Scans patches for CWE vulnerabilities, hardcoded secrets, and suspicious patterns.",
    tools: ["bandit_scan", "secret_detect", "patch_audit"],
    focus: "Security gates & CWE analysis"
  },
  verifier: {
    desc: "Independent Verifier (Shadow Council). Runs in a separate isolated container process to confirm all acceptance criteria pass.",
    tools: ["isolated_sandbox_run", "tamper_detect", "final_attestation"],
    focus: "Independent cryptographic attestation"
  }
};

function NetworkContent({
  id,
  selectedAgent,
  onSelectAgent
}: {
  id: string;
  selectedAgent: string | null;
  onSelectAgent: (agentId: string) => void;
}) {
  const live = useMissionLive(id);
  const activeAgentMeta = AGENTS.find((a) => a.id === selectedAgent);
  const agentRow = live.detail?.agents.find((a) => a.agent_id === selectedAgent);
  const sentMsgs = live.messages.filter((m) => m.sender === selectedAgent);
  const recvMsgs = live.messages.filter((m) => m.recipient === selectedAgent);
  const failedEvents = live.events.filter((e) => e.type === "tool.failed" && e.actor === selectedAgent);

  return (
    <div className="space-y-4">
      <AgentNetworkGraph
        detail={live.detail}
        messages={live.messages}
        events={live.events}
        selectedAgent={selectedAgent}
        onSelectAgent={onSelectAgent}
      />

      {/* Interactive Agent Inspector with Internal Links */}
      {activeAgentMeta && (
        <div className="mx-4 mb-4 rounded-xl border border-accent/40 bg-accent/5 p-4 transition-all">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3">
            <div className="flex items-center gap-2.5">
              <span
                className="grid h-9 w-9 place-items-center rounded-lg shadow-sm"
                style={{ background: `${activeAgentMeta.color}25`, color: activeAgentMeta.color }}
              >
                <activeAgentMeta.Icon className="h-5 w-5" aria-hidden />
              </span>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-fg">{activeAgentMeta.name}</h3>
                  <Badge tone={agentRow?.status === "thinking" ? "running" : agentRow?.last_error ? "danger" : "neutral"}>
                    {agentRow?.status ?? "idle"}
                  </Badge>
                </div>
                <p className="text-xs text-fg3">{activeAgentMeta.role} · {ROLE_DETAILS[activeAgentMeta.id]?.focus}</p>
              </div>
            </div>

            {/* Direct internal navigation buttons */}
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/missions/${id}?agent=${activeAgentMeta.id}&tab=activity`}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white shadow-sm hover:opacity-90 active:scale-95 transition-all"
              >
                <Activity className="h-3.5 w-3.5" />
                View Activity in Mission
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
              <Link
                href={`/missions/${id}?tab=network`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg hover:bg-hover active:scale-95 transition-all"
              >
                Mission Workspace
                <ExternalLink className="h-3.5 w-3.5 text-fg3" />
              </Link>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
            <div className="rounded-lg border border-line bg-surface/60 p-2.5">
              <span className="text-fg3 block text-[11px]">Executions</span>
              <span className="text-base font-semibold text-fg">{agentRow?.executions ?? 0}</span>
            </div>
            <div className="rounded-lg border border-line bg-surface/60 p-2.5">
              <span className="text-fg3 block text-[11px]">Messages Sent</span>
              <span className="text-base font-semibold text-fg">{sentMsgs.length}</span>
            </div>
            <div className="rounded-lg border border-line bg-surface/60 p-2.5">
              <span className="text-fg3 block text-[11px]">Messages Recv</span>
              <span className="text-base font-semibold text-fg">{recvMsgs.length}</span>
            </div>
            <div className="rounded-lg border border-line bg-surface/60 p-2.5">
              <span className="text-fg3 block text-[11px]">Failures / Denials</span>
              <span className={cx("text-base font-semibold", failedEvents.length > 0 ? "text-danger" : "text-fg")}>
                {failedEvents.length}
              </span>
            </div>
          </div>

          {agentRow?.last_error && (
            <div className="mt-3 rounded-lg border border-danger/30 bg-danger/10 p-2.5 text-xs text-danger flex items-start gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Last recorded failure:</span> {agentRow.last_error}
              </div>
            </div>
          )}

          <p className="mt-3 text-xs text-fg2 leading-relaxed">
            {ROLE_DETAILS[activeAgentMeta.id]?.desc}
          </p>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  const { data, loading } = useApi<MissionSummary[]>(() => api.missions.list(), [], 5000);
  const [sel, setSel] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>("planner");
  const ms = data ?? [];
  const current = sel ?? ms.find((m) => ["PLANNING", "EXECUTING", "VERIFYING", "AWAITING_HUMAN", "AWAITING_APPROVAL"].includes(m.status))?.id ?? ms[0]?.id ?? null;

  const handleSelectRole = (agentId: string) => {
    setSelectedAgent(agentId);
    window.scrollTo({ top: 120, behavior: "smooth" });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold">Agent network</h1>
          <p className="text-sm text-fg3">Real message flow between agents for a mission. Click any node to inspect.</p>
        </div>
        <select
          aria-label="Mission"
          className={`${inputCls} ml-auto max-w-xs`}
          value={current ?? ""}
          onChange={(e) => setSel(e.target.value)}
        >
          {ms.map((m) => (
            <option key={m.id} value={m.id}>
              {m.title} · {m.status}
            </option>
          ))}
        </select>
      </div>

      <Card>
        <CardHeader
          title="Topology"
          sub="Interactive node graph. Click any agent node or message edge to inspect live telemetry and filter activity."
        />
        {loading ? (
          <Skeleton className="m-4 h-64" />
        ) : current ? (
          <NetworkContent
            key={current}
            id={current}
            selectedAgent={selectedAgent}
            onSelectAgent={setSelectedAgent}
          />
        ) : (
          <EmptyState title="No missions yet" description="Start a mission to see the agents coordinate." />
        )}
      </Card>

      <Card>
        <CardHeader
          title="Roles & Specifications"
          sub="Click any role to select it in the topology above and navigate directly to its mission activity feed."
        />
        <ul className="divide-y divide-line">
          {AGENTS.map((a) => {
            const isSelected = selectedAgent === a.id;
            const details = ROLE_DETAILS[a.id];
            return (
              <li
                key={a.id}
                id={`role-${a.id}`}
                onClick={() => handleSelectRole(a.id)}
                className={cx(
                  "flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm cursor-pointer transition-colors duration-150 hover:bg-hover",
                  isSelected ? "bg-accent/10 border-l-4 border-accent" : ""
                )}
              >
                <div className="flex items-center gap-3 min-w-[220px]">
                  <span
                    className="grid h-8 w-8 place-items-center rounded-lg"
                    style={{ background: `${a.color}22`, color: a.color }}
                  >
                    <a.Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <div>
                    <div className="flex items-center gap-2">
                      <b className="font-semibold">{a.name}</b>
                      {isSelected && <Badge tone="neutral" className="text-[10px]">Selected</Badge>}
                    </div>
                    <span className="text-xs text-fg3">{a.role}</span>
                  </div>
                </div>

                <div className="flex-1 min-w-[200px] text-xs text-fg2">
                  <p>{details?.desc}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {details?.tools.map((t) => (
                      <Mono key={t} className="text-[10px] text-fg3 bg-elevated px-1.5 py-0.5 rounded border border-line">
                        {t}
                      </Mono>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {current && (
                    <Link
                      href={`/missions/${current}?agent=${a.id}&tab=activity`}
                      onClick={(e) => e.stopPropagation()}
                      className="inline-flex items-center gap-1 rounded-md border border-line bg-surface px-2.5 py-1 text-xs font-medium text-accent hover:border-accent hover:bg-hover transition-all"
                    >
                      Filter Activity
                      <ArrowRight className="h-3 w-3" />
                    </Link>
                  )}
                  <button
                    onClick={() => handleSelectRole(a.id)}
                    className="text-xs text-fg3 hover:text-fg transition-colors"
                  >
                    Select ↑
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
