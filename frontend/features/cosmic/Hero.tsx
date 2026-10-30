"use client";
import { motion } from "framer-motion";
import React from "react";
import { useNow } from "@/lib/useNow";

const greeting = (now: number) => { if (!now) return "Welcome"; const h = new Date(now).getHours(); return h < 5 ? "Good night" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };

/** Cinematic hero: a lit planet limb, an orbital station and nebula, all CSS/SVG (no image downloads, no JS animation loop). */
export function Hero({ name, children }: { name: string; children?: React.ReactNode }) {
  const now = useNow();
  return (
    <section className="glass @container relative overflow-hidden rounded-2xl" aria-label="Welcome">
      <div aria-hidden className="absolute inset-0 bg-[radial-gradient(70%_120%_at_85%_0%,rgba(139,92,246,.35),transparent_60%),radial-gradient(60%_100%_at_0%_100%,rgba(59,130,246,.18),transparent_60%)]" />
      {/* planet limb */}
      <div aria-hidden className="absolute -bottom-[260px] left-[28%] h-[520px] w-[760px] rounded-[50%] bg-[radial-gradient(ellipse_at_50%_0%,#9fd6ff_0%,#3b82f6_8%,#16306e_22%,#070d24_55%)] opacity-90 shadow-[0_-8px_60px_rgba(125,190,255,.55)] max-sm:hidden" />
      <div aria-hidden className="absolute -bottom-[262px] left-[28%] h-[520px] w-[760px] rounded-[50%] border-t-2 border-sky-200/60 blur-[1px] max-sm:hidden" />
      {/* orbital station */}
      <motion.svg aria-hidden viewBox="0 0 200 90" className="absolute right-6 top-4 h-24 w-56 opacity-90 @3xl:right-[320px] max-md:hidden" animate={{ y: [0, -4, 0], rotate: [-1, 1, -1] }} transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }}>
        <ellipse cx="100" cy="46" rx="86" ry="14" fill="none" stroke="#cbd5e1" strokeOpacity=".75" strokeWidth="2" /><ellipse cx="100" cy="46" rx="86" ry="14" fill="none" stroke="#8b5cf6" strokeOpacity=".5" strokeWidth="6" strokeDasharray="2 10" />
        <rect x="88" y="34" width="24" height="24" rx="4" fill="#94a3b8" /><rect x="94" y="14" width="12" height="22" rx="3" fill="#cbd5e1" /><rect x="94" y="56" width="12" height="22" rx="3" fill="#cbd5e1" />
        <circle cx="100" cy="46" r="5" fill="#22d3ee" /><rect x="40" y="38" width="30" height="16" fill="#1e3a8a" stroke="#93c5fd" strokeWidth=".8" /><rect x="130" y="38" width="30" height="16" fill="#1e3a8a" stroke="#93c5fd" strokeWidth=".8" /></motion.svg>
      <div className="relative z-10 grid gap-4 p-5 sm:p-6 @3xl:grid-cols-[1fr_auto]">
        <div>
          <motion.h1 initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="text-2xl font-semibold tracking-tight sm:text-3xl">{greeting(now)}, {name} <span aria-hidden>👋</span></motion.h1>
          <p className="mt-1 max-w-xl text-sm text-fg2 sm:text-base">Orchestrate AI agents to plan, build, test and ship high-quality code, with every claim backed by evidence.</p>
        </div>
        <blockquote className="glass-flat hidden max-w-[280px] self-start rounded-xl border-accent/30 bg-accent/10 p-3 text-sm italic text-fg2 shadow-[0_0_30px_-10px_rgba(139,92,246,.7)] @3xl:block">
          “Plan like a Shogun. Build like a Samurai. Test like a Sentinel. Adapt until the mission is complete.”</blockquote>
      </div>
      {children && <div className="relative z-10 px-5 pb-5 sm:px-6 sm:pb-6">{children}</div>}
    </section>
  );
}
