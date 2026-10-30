"use client";
import { motion } from "framer-motion";
import { Bot, FlaskConical, Rocket } from "lucide-react";
import Link from "next/link";
import React, { useCallback, useState } from "react";
import { useName } from "@/lib/useName";
import { useNow } from "@/lib/useNow";
import { PageMotion } from "@/components/AppShell";
import { Button, Card, CardHeader, EmptyState, Skeleton, Tabs } from "@/components/ui";
import { useActiveMission } from "@/lib/ActiveMission";
import { deriveStages, isActive, missionMetrics } from "@/lib/derive";
import { useMissionLive } from "@/lib/useMission";
import { ActivityFeed } from "../workspace/ActivityFeed";
import { DiffPanel, TestsPanel } from "../workspace/panels";
import { ActiveMissionPanel } from "./ActiveMissionPanel";
import { AgentGuild } from "./AgentGuild";
import { FileView, TerminalPanel, TestResultsMini } from "./DevPanels";
import { Hero } from "./Hero";
import { MetricCards } from "./MetricCards";
import { MissionFlow } from "./MissionFlow";
import { RepoExplorer } from "./RepoExplorer";

type CodeTab = "diff" | "file" | "terminal" | "tests";
const section = (i: number) => ({ initial: { opacity: 0, y: 16 }, animate: { opacity: 1, y: 0 }, transition: { delay: 0.1 + i * 0.07, duration: 0.45 } });

export function Dashboard() {
  const { missions, loading: listLoading, activeId } = useActiveMission();
  // Focus on the running mission; otherwise the most recent one so the dashboard stays informative after a mission ends.
  const focusId = activeId ?? [...missions].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]?.id ?? null;
  return <PageMotion className="mx-auto max-w-[1700px] p-3 sm:p-5">{focusId ? <Live key={focusId} id={focusId} /> : <Body id={null} live={null} listLoading={listLoading} missions={missions} />}</PageMotion>;
}
function Live({ id }: { id: string }) {
  const live = useMissionLive(id);
  const { missions } = useActiveMission();
  return <Body id={id} live={live} listLoading={false} missions={missions} />;
}

function Body({ id, live, listLoading, missions }: { id: string | null; live: ReturnType<typeof useMissionLive> | null; listLoading: boolean; missions: ReturnType<typeof useActiveMission>["missions"] }) {
  const name = useName();
  const [agent, setAgent] = useState<string | null>(null);
  const [tab, setTab] = useState<CodeTab>("diff");
  const [file, setFile] = useState<string | null>(null);
  const d = live?.detail ?? null;
  const events = live?.events ?? [];
  const stages = deriveStages(d, live?.tasks ?? [], live?.tests ?? [], live?.findings ?? [], live?.verification ?? null, events);
  const working = d ? d.agents.filter((a) => a.status === "thinking").length : null;
  const m = missionMetrics(missions, working, useNow());
  const refresh = useCallback(() => void live?.refresh(), [live]);
  const pickFile = (p: string) => { setFile(p); setTab(live?.diffs?.files.some((f) => f.path === p) ? "diff" : "file"); };
  const active = d ? isActive(d.status) : false;

  return (
    <div className="grid gap-4 min-[1380px]:grid-cols-[minmax(0,1fr)_380px]">
      <div className="@container min-w-0 space-y-4">
        <Hero name={name}><MetricCards m={m} /></Hero>

        <motion.div {...section(1)} className="grid gap-4 @4xl:grid-cols-[minmax(0,1fr)_270px]">
          <Card className="min-w-0 overflow-hidden"><CardHeader title="Agent Guild" sub="Multi-agent engineering system: states come from real mission events" />
            <div className="p-3"><AgentGuild detail={d} events={events} live={!!live?.connected && active} selected={agent} onSelect={setAgent} /></div></Card>
          <Card><CardHeader title="Mission Flow" sub="click a stage to see its evidence" /><div className="p-3">{d ? <MissionFlow stages={stages} /> : listLoading ? <Skeleton className="h-64" /> : <p className="py-6 text-center text-sm text-fg3">Start a mission to see its stages.</p>}</div></Card>
        </motion.div>

        <motion.div {...section(2)} className="grid gap-4 @3xl:grid-cols-[220px_minmax(0,1fr)] @6xl:grid-cols-[220px_minmax(0,1fr)_340px]">
          <Card className="min-w-0 overflow-hidden"><RepoExplorer missionId={id} repoName={d?.repository?.github_name ?? d?.repository?.name} selected={file} onSelect={pickFile} version={d?.current_patch_sha256 ?? "none"} /></Card>
          <Card className="min-w-0 overflow-hidden lg:min-h-[320px]"><Tabs<CodeTab> label="Code panels" value={tab} onChange={setTab} tabs={[{ id: "diff", label: "Code Diff" }, { id: "file", label: "File View" }, { id: "terminal", label: "Terminal" }, { id: "tests", label: "Tests" }]} />
            <div className="max-h-[440px] overflow-y-auto">
              {tab === "diff" && (id ? <DiffPanel missionId={id} diffs={live?.diffs ?? null} loading={!!live?.loading} selected={file} onSelect={setFile} /> : <EmptyState title="No changes yet" description="Edits appear here as a real git diff." />)}
              {tab === "file" && <FileView missionId={id} path={file} />}
              {tab === "terminal" && <TerminalPanel missionId={id} toolCalls={live?.toolCalls ?? []} />}
              {tab === "tests" && <TestsPanel runs={live?.tests ?? []} loading={!!live?.loading} />}
            </div></Card>
          <Card className="min-w-0 @3xl:col-span-2 @6xl:col-span-1"><CardHeader title={<span className="flex items-center gap-2"><FlaskConical className="h-4 w-4 text-success" aria-hidden />Test Results</span>} /><TestResultsMini missionId={id} runs={live?.tests ?? []} onViewLogs={() => setTab("terminal")} /></Card>
        </motion.div>
      </div>

      <div className="min-w-0 space-y-4">
        <motion.div {...section(0)}><Card className="p-4"><div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Rocket className="h-4 w-4 text-accent" aria-hidden />Active Mission</div>
          <ActiveMissionPanel d={d} tasks={live?.tasks ?? []} tests={live?.tests ?? []} findings={live?.findings ?? []} verification={live?.verification ?? null} diffs={live?.diffs ?? null} onChanged={refresh} /></Card></motion.div>
        <motion.div {...section(2)}><Card className="flex flex-col"><CardHeader title={<span className="flex items-center gap-2"><Bot className="h-4 w-4 text-cyan" aria-hidden />Agent Conversation</span>} sub={agent ? `filtered to ${agent}` : "decisions, messages and tool calls"} />
          <div className="max-h-[560px] overflow-y-auto">{id ? <ActivityFeed missionId={id} events={events} messages={live?.messages ?? []} toolCalls={live?.toolCalls ?? []} loading={!!live?.loading} filterAgent={agent} onFilterAgent={setAgent} />
            : <EmptyState title="No conversation yet" description="Agents talk to each other through typed, evidenced messages once a mission runs." action={<div className="flex gap-2"><Link href="/missions/new"><Button variant="primary">New mission</Button></Link></div>} />}</div></Card></motion.div>
      </div>
    </div>
  );
}
