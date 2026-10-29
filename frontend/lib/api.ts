import type { Diffs, Decision, DevEvent, Finding, Metrics, MissionDetail, MissionSummary, ModelsConfig, Msg, Repository, Scenario, Task, TestRun, ToolCallRow, Verification, Outcome } from "./types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE = `${API_URL}/api/v1`;

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, unknown> = {}) { super(message); }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, cache: "no-store" });
  } catch {
    throw new ApiError(0, "UNREACHABLE", `Cannot reach the DevPilot backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let body: { error?: { code?: string; message?: string; details?: Record<string, unknown> }; detail?: unknown } = {};
    try { body = await res.json(); } catch { /* not json */ }
    const e = body.error;
    throw new ApiError(res.status, e?.code ?? "ERROR", e?.message ?? (typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`), e?.details ?? {});
  }
  const ct = res.headers.get("content-type") ?? "";
  return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}
const post = <T,>(path: string, body?: unknown) => req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => req<{ status: string }>("/health"),
  config: () => req<ModelsConfig>("/config/models"),
  repos: {
    list: () => req<{ repositories: Repository[] }>("/repositories").then((r) => r.repositories),
    create: (b: { source_type: "LOCAL_PATH" | "GIT_URL"; source_ref: string; branch?: string; github_token?: string; name?: string }) => post<Repository>("/repositories", b),
    parse: (url: string) => req<{ valid: boolean; owner: string | null; name: string | null }>(`/repositories/parse?url=${encodeURIComponent(url)}`),
  },
  demo: {
    scenarios: () => req<{ scenarios: Scenario[]; note: string }>("/demo/scenarios"),
    create: (scenario_id: string) => post<MissionDetail>("/demo/missions", { scenario_id, start: true }),
  },
  missions: {
    list: () => req<{ missions: MissionSummary[] }>("/missions").then((r) => r.missions),
    get: (id: string) => req<MissionDetail>(`/missions/${id}`),
    create: (b: { title: string; prompt: string; repository_id: string; config?: Record<string, unknown>; start?: boolean }) => post<MissionDetail>("/missions", b),
    start: (id: string) => post<MissionDetail>(`/missions/${id}/start`),
    pause: (id: string) => post<MissionDetail>(`/missions/${id}/pause`),
    resume: (id: string) => post<MissionDetail>(`/missions/${id}/resume`),
    cancel: (id: string) => post<MissionDetail>(`/missions/${id}/cancel`),
    respond: (id: string, b: { request_id: string; option?: string; text?: string }) => post<MissionDetail>(`/missions/${id}/respond`, b),
    tasks: (id: string) => req<{ tasks: Task[] }>(`/missions/${id}/tasks`).then((r) => r.tasks),
    messages: (id: string) => req<{ messages: Msg[] }>(`/missions/${id}/messages`).then((r) => r.messages),
    decisions: (id: string) => req<{ decisions: Decision[] }>(`/missions/${id}/decisions`).then((r) => r.decisions),
    toolCalls: (id: string) => req<{ tool_calls: ToolCallRow[] }>(`/missions/${id}/logs`).then((r) => r.tool_calls),
    toolCall: (id: string, tcl: string) => req<ToolCallRow & { full_output: string | null }>(`/missions/${id}/tool-calls/${tcl}`),
    diffs: (id: string) => req<Diffs>(`/missions/${id}/diffs`),
    testRuns: (id: string) => req<{ runs: TestRun[] }>(`/missions/${id}/test-runs`).then((r) => r.runs),
    findings: (id: string) => req<{ findings: Finding[] }>(`/missions/${id}/findings`).then((r) => r.findings),
    waive: (id: string, fid: string, reason: string) => post<{ status: string }>(`/missions/${id}/findings/${fid}/waive`, { reason }),
    verification: (id: string) => req<{ verification: Verification | null }>(`/missions/${id}/verification`).then((r) => r.verification),
    metrics: (id: string) => req<Metrics>(`/missions/${id}/metrics`),
    report: (id: string) => req<{ report: Outcome; final: boolean }>(`/missions/${id}/report`),
    reportMdUrl: (id: string) => `${BASE}/missions/${id}/report?format=md`,
    patchUrl: (id: string) => `${BASE}/missions/${id}/patch`,
    replay: (id: string) => req<{ events: DevEvent[] }>(`/missions/${id}/replay`).then((r) => r.events),
    approve: (id: string, b: { decision: "APPROVED" | "REJECTED" | "CHANGES_REQUESTED"; patch_sha256: string; comment?: string; acknowledged_criteria?: string[];
      publish?: { push: boolean; open_pr: boolean; github_token?: string } }) => post<{ status: string }>(`/missions/${id}/approvals`, b),
    rollback: (id: string) => post<{ rolled_back: boolean }>(`/missions/${id}/rollback`),
    eventsUrl: (id: string) => `${BASE}/missions/${id}/events`,
  },
};
