"use client";
import React, { createContext, useContext } from "react";
import { api } from "./api";
import { isActive } from "./derive";
import type { MissionDetail, MissionSummary, Task, TestRun } from "./types";
import { useApi } from "./useApi";

interface Ctx { missions: MissionSummary[]; loading: boolean; error: string | null; activeId: string | null; detail: MissionDetail | null; tasks: Task[]; tests: TestRun[]; reload: () => void }
const C = createContext<Ctx>({ missions: [], loading: true, error: null, activeId: null, detail: null, tasks: [], tests: [], reload: () => {} });
export const useActiveMission = () => useContext(C);

/** One shared poll of the mission list and of the active mission, used by the shell, the overview and the palette. */
export function ActiveMissionProvider({ children }: { children: React.ReactNode }) {
  const list = useApi<MissionSummary[]>(() => api.missions.list(), [], 4000);
  const ms = list.data ?? [];
  const active = ms.filter((m) => isActive(m.status)).sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
  const activeId = active?.id ?? null;
  const snap = useApi(async () => activeId ? Promise.all([api.missions.get(activeId), api.missions.tasks(activeId), api.missions.testRuns(activeId)]) : null, [activeId, active?.updated_at], 5000);
  const [detail, tasks, tests] = snap.data ?? [null, [], []];
  return <C.Provider value={{ missions: ms, loading: list.loading, error: list.error?.message ?? null, activeId, detail: (detail as MissionDetail | null), tasks: (tasks as Task[]), tests: (tests as TestRun[]), reload: list.reload }}>{children}</C.Provider>;
}
