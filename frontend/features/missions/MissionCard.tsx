"use client";
import { ChevronRight, GitBranch, Wrench } from "lucide-react";
import Link from "next/link";
import { Badge, cx, Github } from "@/components/ui";
import { shortId, timeAgo } from "@/lib/format";
import type { MissionSummary } from "@/lib/types";
import { MissionStatusBadge } from "./status";

export function MissionCard({ m, density = "row" }: { m: MissionSummary; density?: "row" | "card" }) {
  const urgent = m.pending_action;
  return (
    <Link href={`/missions/${m.id}`} className={cx("group flex items-center gap-3 rounded-lg border bg-surface px-4 py-3 transition-colors hover:bg-hover",
      urgent ? "border-approval/40" : "border-line", density === "card" && "flex-col items-start")}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-medium">{m.title}</span><MissionStatusBadge status={m.status} reason={m.status_reason} />
          {m.mode === "scripted" && <Badge tone="neutral" title="Scripted model replay; tools, tests, verifier and gate are real">demo model</Badge>}
          {urgent && <Badge tone="approval">{urgent === "approval" ? "review & approve" : "answer needed"}</Badge>}</div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-fg3">
          <span className="flex items-center gap-1">{m.repository.source_type === "GIT_URL" ? <Github className="h-3 w-3" /> : <GitBranch className="h-3 w-3" />}{m.repository.name ?? "repository"}</span>
          <span className="flex items-center gap-1"><Wrench className="h-3 w-3" />{m.counters.repair_cycles} repair cycle{m.counters.repair_cycles === 1 ? "" : "s"}</span>
          <span>{m.counters.steps} steps</span><span title={m.id} className="font-mono">{shortId(m.id)}</span><span>{timeAgo(m.updated_at)}</span>
        </div>
        {m.status_reason && <p className="mt-1 truncate text-xs text-fg2">{m.status_reason}</p>}
      </div>
      <ChevronRight className="h-4 w-4 shrink-0 text-fg3 transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}
