import { BadgeCheck, Code2, Compass, Crown, FlaskConical, ShieldCheck, type LucideIcon } from "lucide-react";
import type { AgentId } from "@/lib/types";

/** Display identity of each backend agent. Names are presentation only; ids and behaviour are unchanged (AGENTS.md §0.2). */
export interface Guild { id: AgentId | "system" | "human"; name: string; role: string; color: string; glow: string; Icon: LucideIcon }
export const GUILD: Record<string, Guild> = {
  master: { id: "master", name: "DevPilot", role: "Orchestrator", color: "#fbbf24", glow: "251,191,36", Icon: Crown },
  planner: { id: "planner", name: "Shogun", role: "Planner", color: "#f5b942", glow: "245,185,66", Icon: Compass },
  developer: { id: "developer", name: "Samurai", role: "Developer", color: "#3b82f6", glow: "59,130,246", Icon: Code2 },
  tester: { id: "tester", name: "Sentinel", role: "Tester", color: "#10b981", glow: "16,185,129", Icon: FlaskConical },
  security: { id: "security", name: "Shadow", role: "Reviewer", color: "#8b5cf6", glow: "139,92,246", Icon: ShieldCheck },
  verifier: { id: "verifier", name: "Verifier", role: "Independent process", color: "#22d3ee", glow: "34,211,238", Icon: BadgeCheck },
};
export const guild = (id: string): Guild => GUILD[id] ?? { id: "system", name: id === "human" ? "You" : "System", role: id === "human" ? "Human" : "Runtime", color: "#94a3b8", glow: "148,163,184", Icon: Crown };
export const AGENT_ORDER = ["planner", "developer", "tester", "security", "verifier"] as const;
