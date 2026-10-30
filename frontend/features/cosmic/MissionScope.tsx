"use client";
import React, { useState } from "react";
import { PageMotion } from "@/components/AppShell";
import { EmptyState, inputCls } from "@/components/ui";
import { useActiveMission } from "@/lib/ActiveMission";
import { useMissionLive } from "@/lib/useMission";
import Link from "next/link";
import { Button } from "@/components/ui";

/** Shared frame for the cross-mission pages (Terminal, Tests, Security): pick a mission, render a live view of it. */
export function MissionScope({ title, subtitle, children }: { title: string; subtitle: string; children: (live: ReturnType<typeof useMissionLive>, id: string) => React.ReactNode }) {
  const { missions, activeId } = useActiveMission();
  const [sel, setSel] = useState<string | null>(null);
  const sorted = [...missions].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const id = sel ?? activeId ?? sorted[0]?.id ?? null;
  return (
    <PageMotion className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-3"><div><h1 className="text-xl font-semibold">{title}</h1><p className="text-sm text-fg3">{subtitle}</p></div>
        {sorted.length > 0 && <select aria-label="Mission" className={`${inputCls} ml-auto max-w-xs`} value={id ?? ""} onChange={(e) => setSel(e.target.value)}>{sorted.map((m) => <option key={m.id} value={m.id}>{m.title} · {m.status.toLowerCase().replace("_", " ")}</option>)}</select>}</div>
      {id ? <Inner key={id} id={id}>{children}</Inner> : <div className="glass rounded-xl"><EmptyState title="No missions yet" description="Run a mission and its evidence shows up here." action={<Link href="/missions/new"><Button variant="primary">New mission</Button></Link>} /></div>}
    </PageMotion>
  );
}
function Inner({ id, children }: { id: string; children: (live: ReturnType<typeof useMissionLive>, id: string) => React.ReactNode }) {
  const live = useMissionLive(id);
  return <>{children(live, id)}</>;
}
