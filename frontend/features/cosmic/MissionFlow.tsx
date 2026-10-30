"use client";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Check, ChevronDown, Lock, X } from "lucide-react";
import React, { useState } from "react";
import { Mono, cx } from "@/components/ui";
import type { Stage, StageState } from "@/lib/derive";
import { shortId } from "@/lib/format";

const STYLE: Record<StageState, { ring: string; label: string }> = {
  completed: { ring: "border-success bg-success/20 text-success", label: "completed" }, active: { ring: "border-accent bg-accent/30 text-fg shadow-[0_0_14px_rgba(139,92,246,.8)]", label: "in progress" },
  pending: { ring: "border-line-strong text-fg3", label: "pending" }, failed: { ring: "border-danger bg-danger/20 text-danger", label: "failed" }, blocked: { ring: "border-warning bg-warning/15 text-warning", label: "blocked" },
};

/** The 7 workflow stages from real state. Click a stage to inspect the evidence behind it. */
export function MissionFlow({ stages }: { stages: Stage[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <ol aria-label="Mission flow" className="relative space-y-0.5">
      <div aria-hidden className="absolute bottom-3 left-[13px] top-3 w-px bg-gradient-to-b from-accent/60 via-line to-transparent" />
      {stages.map((s, i) => {
        const st = STYLE[s.state], isOpen = open === s.id;
        return (
          <li key={s.id}>
            <button onClick={() => setOpen(isOpen ? null : s.id)} aria-expanded={isOpen} aria-label={`${i + 1}. ${s.label}: ${st.label}`}
              className={cx("relative flex w-full items-center gap-3 rounded-lg px-1 py-1.5 text-left transition-colors hover:bg-hover", s.state === "active" && "bg-accent/10")}>
              <span className={cx("relative z-10 grid h-[26px] w-[26px] shrink-0 place-items-center rounded-full border text-[11px] font-semibold", st.ring)}>
                {s.state === "completed" ? <Check className="h-3.5 w-3.5" aria-hidden /> : s.state === "failed" ? <X className="h-3.5 w-3.5" aria-hidden /> : s.state === "blocked" ? <Lock className="h-3 w-3" aria-hidden /> : i + 1}
                {s.state === "active" && <span aria-hidden className="pulse-ring text-accent" />}</span>
              <span className="min-w-0 flex-1"><span className={cx("block text-sm", s.state === "pending" ? "text-fg3" : "text-fg")}>{s.label}</span>
                {s.state !== "pending" && <span className={cx("block text-[10px] uppercase tracking-wide", s.state === "failed" ? "text-danger" : s.state === "blocked" ? "text-warning" : "text-fg3")}>{st.label}</span>}</span>
              <ChevronDown className={cx("h-3.5 w-3.5 text-fg3 transition-transform", isOpen && "rotate-180")} aria-hidden />
            </button>
            <AnimatePresence initial={false}>{isOpen && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                <ul className="mb-1 ml-10 space-y-1 border-l border-line pl-3 pt-1 text-xs text-fg2">
                  {s.evidence.length === 0 ? <li className="flex items-center gap-1.5 text-fg3"><AlertTriangle className="h-3 w-3" aria-hidden />No evidence recorded for this stage yet.</li>
                    : s.evidence.slice(0, 8).map((e, k) => <li key={k} className="flex items-start gap-2"><span className="min-w-0 flex-1 break-words">{e.label}</span>{e.id && <Mono className="shrink-0 text-fg3">{shortId(e.id)}</Mono>}</li>)}
                  {s.evidence.length > 8 && <li className="text-fg3">+{s.evidence.length - 8} more</li>}</ul></motion.div>)}</AnimatePresence>
          </li>);
      })}
    </ol>
  );
}
