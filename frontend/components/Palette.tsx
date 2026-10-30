"use client";
import { AnimatePresence, motion } from "framer-motion";
import { Bot, FileText, GitBranch, History, LayoutDashboard, ListChecks, Moon, Network, Plus, Search, Settings, ShieldAlert, Terminal, FlaskConical, ClipboardCheck, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Repository } from "@/lib/types";
import { useActiveMission } from "@/lib/ActiveMission";
import { cx } from "./ui";

interface Item { id: string; group: string; label: string; hint?: string; icon: React.ReactNode; run: () => void }

/** ⌘K / Ctrl+K command palette over REAL data: pages, missions, repositories and actions. */
export function Palette({ open, onClose, toggleTheme }: { open: boolean; onClose: () => void; toggleTheme: () => void }) {
  const router = useRouter();
  const { missions } = useActiveMission();
  const [repos, setRepos] = useState<Repository[]>([]);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { if (open) { api.repos.list().then(setRepos).catch(() => setRepos([])); setTimeout(() => input.current?.focus(), 30); } }, [open]);
  const go = (href: string) => () => { router.push(href); onClose(); };
  const items: Item[] = useMemo(() => [
    { id: "new", group: "Actions", label: "New mission", hint: "describe a change", icon: <Plus className="h-4 w-4" />, run: go("/missions/new") },
    { id: "import", group: "Actions", label: "Import a run log (.jsonl)", hint: "replay a saved run", icon: <Upload className="h-4 w-4" />, run: go("/history#import") },
    { id: "theme", group: "Actions", label: "Toggle light / dark theme", icon: <Moon className="h-4 w-4" />, run: () => { toggleTheme(); onClose(); } },
    ...([["/", "Overview", LayoutDashboard], ["/missions", "Missions", ListChecks], ["/agents", "Agent Network", Network], ["/repositories", "Repositories", GitBranch], ["/terminal", "Terminal", Terminal],
      ["/tests", "Tests", FlaskConical], ["/security", "Security", ShieldAlert], ["/evaluation", "Evaluation", ClipboardCheck], ["/history", "Execution History", History], ["/reports", "Reports", FileText], ["/settings", "Settings", Settings]] as const)
      .map(([href, label, Icon]) => ({ id: `p${href}`, group: "Go to", label, icon: <Icon className="h-4 w-4" />, run: go(href) })),
    ...missions.slice(0, 20).map((m) => ({ id: m.id, group: "Missions", label: m.title, hint: `${m.status.toLowerCase().replace("_", " ")} · ${m.repository.name ?? ""}`, icon: <Bot className="h-4 w-4" />, run: go(`/missions/${m.id}`) })),
    ...repos.slice(0, 20).map((r) => ({ id: r.id, group: "Repositories", label: r.github_owner ? `${r.github_owner}/${r.github_name}` : r.name, hint: r.source_type === "GIT_URL" ? "GitHub" : "local", icon: <GitBranch className="h-4 w-4" />, run: go("/repositories") })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [missions, repos]);
  const shown = items.filter((i) => !q.trim() || `${i.label} ${i.hint ?? ""} ${i.group}`.toLowerCase().includes(q.toLowerCase()));
  const sel = Math.min(idx, Math.max(shown.length - 1, 0));

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((sel + 1) % Math.max(shown.length, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((sel - 1 + shown.length) % Math.max(shown.length, 1)); }
    else if (e.key === "Enter") { e.preventDefault(); shown[sel]?.run(); }
    else if (e.key === "Escape") onClose();
  };
  return (
    <AnimatePresence>{open && (
      <motion.div className="fixed inset-0 z-[70] flex items-start justify-center bg-black/60 p-4 pt-[12vh] backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
        <motion.div role="dialog" aria-modal="true" aria-label="Command palette" initial={{ y: -12, scale: 0.97 }} animate={{ y: 0, scale: 1 }} exit={{ y: -8, opacity: 0 }}
          className="glass w-full max-w-xl overflow-hidden rounded-xl shadow-[0_24px_80px_rgba(0,0,0,.6)]" onKeyDown={onKey}>
          <div className="flex items-center gap-2 border-b border-line px-3"><Search className="h-4 w-4 text-fg3" aria-hidden />
            <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setIdx(0); }} placeholder="Search missions, repositories, pages and actions…" aria-label="Search" className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-fg3" role="combobox" aria-expanded aria-controls="pal-list" aria-activedescendant={shown[sel] ? `pal-${shown[sel].id}` : undefined} />
            <kbd className="rounded border border-line px-1.5 text-[10px] text-fg3">esc</kbd></div>
          <ul id="pal-list" role="listbox" className="max-h-[50vh] overflow-y-auto p-1">
            {shown.length === 0 && <li className="px-3 py-6 text-center text-sm text-fg3">Nothing matches “{q}”.</li>}
            {shown.map((it, i) => (
              <li key={it.id} id={`pal-${it.id}`} role="option" aria-selected={i === sel}>
                {(i === 0 || shown[i - 1].group !== it.group) && <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-fg3">{it.group}</div>}
                <button onMouseEnter={() => setIdx(i)} onClick={it.run} className={cx("flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm", i === sel ? "bg-accent/20 text-fg" : "text-fg2")}>
                  <span className="text-fg3">{it.icon}</span><span className="min-w-0 flex-1 truncate">{it.label}</span>{it.hint && <span className="truncate text-xs text-fg3">{it.hint}</span>}</button></li>))}
          </ul>
        </motion.div></motion.div>)}</AnimatePresence>
  );
}
