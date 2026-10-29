"use client";
import { AlertOctagon, Ban, BadgeCheck, CheckCircle2, Circle, Compass, GitPullRequest, Loader, MessageCircleQuestion, Pause, XCircle } from "lucide-react";
import { Badge, type Tone } from "@/components/ui";
import type { MissionStatus } from "@/lib/types";

const MAP: Record<MissionStatus, { tone: Tone; icon: React.ReactNode; label: string }> = {
  CREATED: { tone: "neutral", icon: <Circle className="h-3 w-3" />, label: "Created" },
  PLANNING: { tone: "running", icon: <Compass className="h-3 w-3" />, label: "Planning" },
  EXECUTING: { tone: "running", icon: <Loader className="h-3 w-3" />, label: "Executing" },
  VERIFYING: { tone: "running", icon: <BadgeCheck className="h-3 w-3" />, label: "Verifying" },
  AWAITING_HUMAN: { tone: "warning", icon: <MessageCircleQuestion className="h-3 w-3" />, label: "Needs your input" },
  AWAITING_APPROVAL: { tone: "approval", icon: <GitPullRequest className="h-3 w-3" />, label: "Awaiting approval" },
  PAUSED: { tone: "warning", icon: <Pause className="h-3 w-3" />, label: "Paused" },
  COMPLETED: { tone: "success", icon: <CheckCircle2 className="h-3 w-3" />, label: "Completed" },
  REJECTED: { tone: "danger", icon: <XCircle className="h-3 w-3" />, label: "Rejected" },
  FAILED: { tone: "danger", icon: <AlertOctagon className="h-3 w-3" />, label: "Failed" },
  CANCELLED: { tone: "neutral", icon: <Ban className="h-3 w-3" />, label: "Cancelled" },
};
export function MissionStatusBadge({ status, reason }: { status: MissionStatus; reason?: string | null }) {
  const m = MAP[status] ?? MAP.CREATED;
  return <span role="status"><Badge tone={m.tone} icon={m.icon} title={reason ?? undefined}>{m.label}</Badge></span>;
}

export const SEV_TONE: Record<string, Tone> = { INFO: "neutral", LOW: "neutral", MEDIUM: "warning", HIGH: "danger", CRITICAL: "critical" };
export const TASK_TONE: Record<string, Tone> = { PENDING: "neutral", READY: "accent", IN_PROGRESS: "running", BLOCKED: "warning", IN_REVIEW: "approval", DONE: "success", FAILED: "danger", CANCELLED: "neutral", SUPERSEDED: "neutral" };
export const CRIT_TONE: Record<string, Tone> = { UNVERIFIED: "neutral", PASS: "success", FAIL: "danger", INCONCLUSIVE: "warning" };
