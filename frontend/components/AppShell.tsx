"use client";
import { MotionConfig, motion } from "framer-motion";
import { Check, ClipboardCheck, FileText, FlaskConical, GitBranch, History, LayoutDashboard, ListChecks, Moon, Network, OctagonX, Search, Settings, ShieldAlert, ShieldCheck, Sparkles, Sun, Terminal, UserRound } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { Suspense, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ActiveMissionProvider, useActiveMission } from "@/lib/ActiveMission";
import { deriveStages } from "@/lib/derive";
import type { ModelsConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Palette } from "./Palette";
import { ToastProvider, useToast } from "./Toast";
import { Badge, cx } from "./ui";

export const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard }, { href: "/missions", label: "Missions", icon: ListChecks }, { href: "/agents", label: "Agent Network", icon: Network },
  { href: "/repositories", label: "Repositories", icon: GitBranch }, { href: "/terminal", label: "Terminal", icon: Terminal }, { href: "/tests", label: "Tests", icon: FlaskConical },
  { href: "/security", label: "Security", icon: ShieldAlert }, { href: "/evaluation", label: "Evaluation", icon: ClipboardCheck }, { href: "/history", label: "Execution History", icon: History },
  { href: "/reports", label: "Reports", icon: FileText }, { href: "/settings", label: "Settings", icon: Settings },
];

function ThemeIcon() { return (<><Sun className="hidden h-4 w-4 [[data-theme=dark]_&]:block" aria-hidden /><Moon className="h-4 w-4 [[data-theme=dark]_&]:hidden" aria-hidden /></>); }
function Logo() {
  return (
    <div className="relative grid h-10 w-10 place-items-center rounded-xl border border-accent/40 bg-gradient-to-br from-accent/30 to-cyan/10 shadow-[0_0_24px_rgba(139,92,246,.45)]">
      <Sparkles className="h-5 w-5 text-fg" aria-hidden /></div>
  );
}

// usePathname() needs a Suspense boundary on dynamic routes (Cache Components); only the nav depends on it.
function SideNav({ attention }: { attention: number }) {
  const path = usePathname();
  return (
    <nav aria-label="Primary" className="flex-1 space-y-0.5 overflow-y-auto p-3">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link key={href} href={href} aria-current={active ? "page" : undefined}
            className={cx("group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-all", active ? "bg-gradient-to-r from-accent/35 to-accent/5 text-fg shadow-[0_0_20px_-4px_rgba(139,92,246,.55)] ring-1 ring-accent/40" : "text-fg2 hover:bg-hover hover:text-fg")}>
            <Icon className={cx("h-4 w-4 transition-transform group-hover:scale-110", active && "text-fg")} aria-hidden />{label}
            {label === "Missions" && attention > 0 && <Badge tone="approval" className="ml-auto" title="missions waiting for you">{attention}</Badge>}
          </Link>);
      })}
    </nav>
  );
}

const MOBILE = ["/", "/missions", "/agents", "/terminal", "/settings"];
function MobileNav() {
  const path = usePathname();
  return (
    <nav aria-label="Primary (mobile)" className="glass fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 rounded-none border-x-0 border-b-0 md:hidden">
      {NAV.filter((n) => MOBILE.includes(n.href)).map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return <Link key={href} href={href} aria-current={active ? "page" : undefined} className={cx("flex flex-col items-center gap-0.5 py-2 text-[11px]", active ? "text-cyan" : "text-fg3")}><Icon className="h-4 w-4" aria-hidden />{label.split(" ")[0]}</Link>;
      })}
    </nav>
  );
}

function CurrentMission() {
  const { detail, tasks, tests, activeId, reload } = useActiveMission();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!detail || !activeId) return <div className="m-3 rounded-lg border border-line p-3 text-xs text-fg3">No active mission. <Link href="/missions/new" className="text-cyan underline">Start one</Link>.</div>;
  const st = deriveStages(detail, tasks, tests, [], null, []);
  const S = detail.status;
  const review = S === "AWAITING_APPROVAL" || S === "COMPLETED" ? "completed" : S === "VERIFYING" ? "active" : st[5].state === "failed" ? "failed" : "pending";
  const approval = S === "COMPLETED" ? "completed" : S === "AWAITING_APPROVAL" ? "active" : S === "REJECTED" ? "failed" : "pending";
  const mini = [["Planning", st[2]], ["Implementation", st[3]], ["Testing", st[4]], ["Review", { state: review }], ["Approval", { state: approval }]] as const;
  const done = tasks.filter((t) => t.status === "DONE").length, total = tasks.filter((t) => t.status !== "SUPERSEDED").length;
  async function stop() {
    if (!confirm("Stop this mission? Evidence is kept; your repository is not changed.")) return;
    setBusy(true);
    try { await api.missions.cancel(activeId!); toast("info", "Mission stopped. Evidence was kept."); reload(); } catch (e) { toast("error", (e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="m-3 rounded-xl border border-line bg-black/20 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-fg3">Current mission</div>
      <Link href={`/missions/${activeId}`} className="mt-1 block truncate text-sm font-semibold hover:text-cyan">{detail.title}</Link>
      <div className="mt-1.5 flex items-center gap-2"><div className="h-1.5 flex-1 overflow-hidden rounded bg-hover" role="progressbar" aria-label="Mission progress" aria-valuenow={done} aria-valuemax={total || 1}>
        <motion.div className="h-full rounded bg-gradient-to-r from-accent to-cyan" initial={false} animate={{ width: total ? `${(100 * done) / total}%` : "4%" }} /></div><span className="text-[11px] text-fg3">{done}/{total || "—"}</span></div>
      <ul className="mt-2 space-y-1">{mini.map(([l, s]) => (
        <li key={l} className="flex items-center gap-2 text-xs"><span className={cx("grid h-4 w-4 place-items-center rounded-full border", s.state === "completed" ? "border-success bg-success/20 text-success" : s.state === "active" ? "border-accent bg-accent/30 text-fg" : s.state === "failed" ? "border-danger text-danger" : s.state === "blocked" ? "border-warning text-warning" : "border-line-strong text-transparent")}>
          {s.state === "completed" ? <Check className="h-2.5 w-2.5" /> : s.state === "active" ? <span className="dp-pulse h-1.5 w-1.5 rounded-full bg-accent" /> : null}</span>
          <span className={s.state === "pending" ? "text-fg3" : "text-fg2"}>{l}</span></li>))}</ul>
      <button onClick={stop} disabled={busy} className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-danger/50 bg-danger/15 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger/25 disabled:opacity-50"><OctagonX className="h-4 w-4" aria-hidden />Stop Mission</button>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const [palette, setPalette] = useState(false);
  const toggle = useCallback(() => { const t = document.documentElement.dataset.theme === "light" ? "dark" : "light"; localStorage.setItem("dp-theme", t); document.documentElement.dataset.theme = t; }, []);
  const { missions, error } = useActiveMission();
  const { data: cfg } = useApi<ModelsConfig>(() => api.config(), []);
  const attention = missions.filter((m) => m.pending_action).length;
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); } };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, []);
  return (
    <MotionConfig reducedMotion="user">
      <div className="starfield" aria-hidden />
      <div className="relative z-10 flex min-h-screen flex-col md:flex-row">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-1 focus:text-accent-fg">Skip to content</a>
        <aside className="glass sticky top-0 hidden h-screen w-60 shrink-0 flex-col rounded-none border-y-0 border-l-0 md:flex lg:w-64">
          <div className="flex h-[68px] items-center gap-3 border-b border-line px-4"><Logo /><div className="min-w-0 leading-tight"><div className="text-lg font-semibold tracking-tight">DevPilot</div><div className="truncate text-[10px] text-fg3">Mystic Mikado&apos;s Engineering Guild</div></div></div>
          <Suspense fallback={<nav aria-label="Primary" className="flex-1" />}><SideNav attention={attention} /></Suspense>
          <CurrentMission />
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="glass sticky top-0 z-30 flex min-h-[68px] flex-wrap items-center gap-x-4 gap-y-2 rounded-none border-x-0 border-t-0 px-4 py-2">
            <div className="flex items-center gap-2 md:hidden"><Logo /><span className="text-sm font-semibold">DevPilot</span></div>
            <div className="hidden min-w-0 md:block"><div className="text-lg font-semibold leading-tight">DevPilot</div><div className="truncate text-[11px] text-fg3">The Mystic Mikado&apos;s Autonomous AI Engineering Guild</div></div>
            <button onClick={() => setPalette(true)} className="mx-auto flex h-10 min-w-0 flex-1 basis-56 items-center gap-2 rounded-xl border border-line bg-black/20 px-3 text-left text-sm text-fg3 transition-colors hover:border-accent/50 md:max-w-md" aria-label="Open search (Command K)">
              <Search className="h-4 w-4 shrink-0" aria-hidden /><span className="min-w-0 flex-1 truncate">Search missions, repositories, agents…</span><kbd className="hidden rounded border border-line px-1.5 text-[10px] sm:block">⌘ K</kbd></button>
            <div className="ml-auto flex flex-wrap items-center justify-end gap-1.5">
              {cfg && <Badge tone="warning" icon={<ShieldCheck className="h-3 w-3" />} title={cfg.sandbox_note}>sandbox: {cfg.sandbox_mode.replace("_", "-")}</Badge>}
              {cfg && <Badge tone={cfg.live_available ? "success" : "neutral"} icon={<span className={cx("h-1.5 w-1.5 rounded-full", cfg.live_available ? "bg-success" : "bg-neutral")} />} title={cfg.live_available ? "A live model provider is configured" : "No model key configured: only scripted demo missions can run"}>{cfg.live_available ? "live model" : "demo model only"}</Badge>}
              <button onClick={toggle} aria-label="Toggle light/dark theme" className="rounded-lg p-2 text-fg2 hover:bg-hover"><ThemeIcon /></button>
              <span className="grid h-9 w-9 place-items-center rounded-full border border-accent/40 bg-gradient-to-br from-accent/40 to-cyan/20" title="Local user (accounts are not implemented yet)"><UserRound className="h-4 w-4" aria-hidden /></span>
            </div>
          </header>
          {error && <div role="alert" className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">Cannot reach the DevPilot backend. Start it (<code className="font-mono">docker compose up -d</code> or <code className="font-mono">uvicorn app.main:app --port 8000</code>).</div>}
          <main id="main" className="min-w-0 flex-1 pb-20 md:pb-0">{children}</main>
        </div>
        <Suspense fallback={null}><MobileNav /></Suspense>
      </div>
      <Palette open={palette} onClose={() => setPalette(false)} toggleTheme={toggle} />
    </MotionConfig>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return <ToastProvider><ActiveMissionProvider><Shell>{children}</Shell></ActiveMissionProvider></ToastProvider>;
}

/** Entrance animation for every page (runs on each navigation because the page remounts). */
export function PageMotion({ children, className }: { children: React.ReactNode; className?: string }) {
  return <motion.div className={className} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28, ease: [0.2, 0.8, 0.2, 1] }}>{children}</motion.div>;
}
