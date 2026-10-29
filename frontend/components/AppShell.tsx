"use client";
import { Activity, ClipboardCheck, FileText, GitBranch, History, LayoutDashboard, ListChecks, Moon, Network, Settings, ShieldAlert, ShieldCheck, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { Suspense } from "react";
import { api } from "@/lib/api";
import type { ModelsConfig, MissionSummary } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { Badge, cx } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard }, { href: "/missions", label: "Missions", icon: ListChecks }, { href: "/agents", label: "Agent Network", icon: Network },
  { href: "/repositories", label: "Repositories", icon: GitBranch }, { href: "/evaluation", label: "Evaluation", icon: ClipboardCheck }, { href: "/history", label: "Execution History", icon: History }, { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
];

function ThemeIcon() {
  return (<><Sun className="hidden h-4 w-4 [[data-theme=dark]_&]:block" aria-hidden /><Moon className="h-4 w-4 [[data-theme=dark]_&]:hidden" aria-hidden /></>);
}

// usePathname() needs a Suspense boundary on dynamic routes (Cache Components); only the nav depends on it.
function SideNav({ attention }: { attention: number }) {
  const path = usePathname();
  return (
    <nav aria-label="Primary" className="flex-1 space-y-0.5 p-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link key={href} href={href} aria-current={active ? "page" : undefined}
                className={cx("flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors", active ? "bg-hover text-fg" : "text-fg2 hover:bg-hover hover:text-fg")}>
                <Icon className="h-4 w-4" aria-hidden />{label}
                {label === "Missions" && attention > 0 && <Badge tone="approval" className="ml-auto" title="missions waiting for you">{attention}</Badge>}
              </Link>
            );
          })}
    </nav>
  );
}

function MobileNav() {
  const path = usePathname();
  return (
    <nav aria-label="Primary (mobile)" className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-surface md:hidden">
        {[NAV[0], NAV[1], NAV[2], NAV[3], NAV[7]].map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return <Link key={href} href={href} aria-current={active ? "page" : undefined} className={cx("flex flex-col items-center gap-0.5 py-2 text-[11px]", active ? "text-accent" : "text-fg3")}><Icon className="h-4 w-4" aria-hidden />{label.split(" ")[0]}</Link>;
        })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  // The layout script applies the saved theme before paint; the toggle reads/writes the DOM, so no state is needed.
  const toggle = () => { const t = document.documentElement.dataset.theme === "light" ? "dark" : "light"; localStorage.setItem("dp-theme", t); document.documentElement.dataset.theme = t; };
  const { data: ms, error } = useApi<MissionSummary[]>(() => api.missions.list(), [], 5000);
  const { data: cfg } = useApi<ModelsConfig>(() => api.config(), []);
  const attention = (ms ?? []).filter((m) => m.pending_action).length;
  const running = (ms ?? []).filter((m) => ["PLANNING", "EXECUTING", "VERIFYING"].includes(m.status)).length;

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-1 focus:text-accent-fg">Skip to content</a>
      <aside className="hidden w-56 shrink-0 flex-col border-r border-line bg-surface md:flex lg:w-60">
        <div className="flex h-14 items-center gap-2 border-b border-line px-4">
          <div className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-fg"><Activity className="h-4 w-4" aria-hidden /></div>
          <div className="leading-tight"><div className="text-sm font-semibold">DevPilot</div><div className="text-[11px] text-fg3">Engineering guild</div></div>
        </div>
        <Suspense fallback={<nav aria-label="Primary" className="flex-1" />}><SideNav attention={attention} /></Suspense>
        <div className="space-y-2 border-t border-line p-3 text-xs text-fg3">
          <div className="flex items-center justify-between"><span>{running} running</span>
            <button onClick={toggle} aria-label="Toggle light/dark theme" className="rounded p-1.5 hover:bg-hover"><ThemeIcon /></button></div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line bg-canvas/90 px-4 py-2 backdrop-blur">
          <div className="flex items-center gap-2 md:hidden"><div className="grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-fg"><Activity className="h-4 w-4" aria-hidden /></div><span className="text-sm font-semibold">DevPilot</span></div>
          <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1.5">
            {cfg && (
              <Badge
                tone={cfg.sandbox_mode === "container_isolated" || cfg.sandbox_mode === "docker_jail" ? "success" : "warning"}
                icon={cfg.sandbox_mode === "container_isolated" || cfg.sandbox_mode === "docker_jail" ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
                title={cfg.sandbox_note}
              >
                sandbox: {cfg.sandbox_mode.replace("_", "-")}
              </Badge>
            )}
            {cfg && <Badge tone={cfg.live_available ? "success" : "neutral"} title={cfg.live_available ? "A live model provider is configured" : "No model key configured: only scripted demo missions can run"}>{cfg.live_available ? "live model" : "demo model only"}</Badge>}
            <button onClick={toggle} aria-label="Toggle light/dark theme" className="rounded p-1.5 text-fg2 hover:bg-hover md:hidden"><ThemeIcon /></button>
          </div>
        </header>
        {error?.code === "UNREACHABLE" && (
          <div role="alert" className="border-b border-danger/30 bg-danger/10 px-4 py-2 text-sm text-danger">Cannot reach the DevPilot backend ({error.message.split(" at ")[1]?.split(".")[0] ?? "backend"}). Start it with <code className="font-mono">uvicorn app.main:app --port 8000</code> in <code className="font-mono">backend/</code>.</div>
        )}
        <main id="main" className="min-w-0 flex-1 pb-20 md:pb-0">{children}</main>
      </div>

      <Suspense fallback={null}><MobileNav /></Suspense>
    </div>
  );
}
