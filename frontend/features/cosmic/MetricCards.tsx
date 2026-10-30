"use client";
import { motion } from "framer-motion";
import { Bot, CheckCircle2, Clock, Rocket } from "lucide-react";
import React from "react";
import { fmtDuration, type Metrics4 } from "@/lib/derive";

function Spark({ data, color }: { data: number[]; color: string }) {
  const max = Math.max(...data, 1);
  const pts = data.map((v, i) => `${(i / (data.length - 1)) * 100},${28 - (v / max) * 24}`).join(" ");
  return <svg viewBox="0 0 100 30" className="h-8 w-24" aria-hidden><polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" style={{ filter: `drop-shadow(0 0 4px ${color})` }} /></svg>;
}

/** Four metrics, all derived from real missions. A sparkline only appears once there is history to draw. */
export function MetricCards({ m }: { m: Metrics4 }) {
  const cards = [
    { k: "Total Missions", v: String(m.total), sub: m.total ? `${m.thisWeek} in the last 7 days` : "no missions yet", icon: Rocket, color: "#8b5cf6", spark: m.perDay },
    { k: "Successful", v: String(m.successful), sub: m.successRate != null ? `${m.successRate}% of finished missions` : "nothing finished yet", icon: CheckCircle2, color: "#10b981", spark: null },
    { k: "Avg. Completion", v: fmtDuration(m.avgMs), sub: m.avgMs != null ? "created → applied, completed missions" : "needs a completed mission", icon: Clock, color: "#22d3ee", spark: null },
    { k: "Active Agents", v: m.activeAgents == null ? "0" : String(m.activeAgents), sub: "5 specialists + 1 orchestrator", icon: Bot, color: "#fbbf24", spark: null },
  ];
  return (
    <div className="@container grid grid-cols-2 gap-3 @2xl:grid-cols-4">
      {cards.map((c, i) => (
        <motion.div key={c.k} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 * i, duration: 0.4 }} whileHover={{ y: -3 }}
          className="glass-flat group relative overflow-hidden rounded-xl p-3.5 transition-shadow hover:shadow-[0_0_30px_-8px_var(--c)]" style={{ "--c": c.color } as React.CSSProperties}>
          <div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="flex items-center gap-1.5 text-xs text-fg2"><c.icon className="h-3.5 w-3.5" style={{ color: c.color }} aria-hidden />{c.k}</div>
            <div className={`mt-1 font-semibold tabular-nums ${c.v.length > 5 ? "text-lg" : "text-2xl @lg:text-3xl"}`}>{c.v}</div></div>{c.spark && <Spark data={c.spark} color={c.color} />}</div>
          <div className="mt-1 text-[11px] text-fg3">{c.sub}</div>
        </motion.div>))}
    </div>
  );
}
