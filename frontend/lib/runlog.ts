import type { DevEvent } from "./types";

/** Parse a JSONL run log into events. Accepts DevPilot's own events.jsonl and the legacy prototype format
 *  ({time, agent, event_type, tool, input, output_summary, message_type, payload}). Throws a readable error on bad input. */
export function parseRunLog(text: string): { events: DevEvent[]; format: "devpilot" | "legacy" } {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (!lines.length) throw new Error("The file is empty.");
  if (lines.length > 20000) throw new Error("Too large: at most 20,000 events.");
  const rows = lines.map((l, i) => { try { return JSON.parse(l) as Record<string, unknown>; } catch { throw new Error(`Line ${i + 1} is not valid JSON.`); } });
  if (rows.every((r) => typeof r.type === "string" && "payload" in r)) {
    return { format: "devpilot", events: rows.map((r, i) => ({ id: String(r.id ?? `imp_${i}`), type: String(r.type), actor: String(r.actor ?? "system"), task_id: (r.task_id as string) ?? null, created_at: String(r.created_at ?? new Date(0).toISOString()), payload: (r.payload ?? {}) as Record<string, unknown> })) };
  }
  if (rows.every((r) => typeof r.event_type === "string" && typeof r.agent === "string")) {
    const actor = (a: string) => ({ planner: "planner", developer: "developer", verifier: "tester", reviewer: "security", safety: "system", orchestrator: "master", human: "human" }[a] ?? "system");
    const sorted = [...rows].sort((a, b) => Number(a.time ?? 0) - Number(b.time ?? 0));
    return {
      format: "legacy", events: sorted.map((r, i) => {
        const who = actor(String(r.agent)), t = String(r.event_type), sum = String(r.output_summary ?? ""), pl = (r.payload ?? {}) as Record<string, unknown>;
        const at = new Date(Date.UTC(2000, 0, 1) + Number(r.time ?? i) * 1000).toISOString();
        const base = { id: `imp_${String(i).padStart(5, "0")}`, actor: who, task_id: null, created_at: at };
        if (t === "tool.call") return { ...base, type: "tool.completed", payload: { tool: r.tool ?? "tool", args_summary: JSON.stringify(r.input ?? {}).slice(0, 120), status: "OK", tool_call_id: base.id, exit_code: null } };
        if (t === "test.result") return { ...base, type: Number(pl.exit_code) === 0 ? "test.passed" : "test.failed", payload: { kind: "TEST", command: String((r.input as { command?: string } | null)?.command ?? "tests"), summary: { total: 0 }, outcome: Number(pl.exit_code) === 0 ? "GREEN" : "RED", note: sum } };
        if (t === "command.blocked") return { ...base, type: "policy.denied", payload: { tool: r.tool ?? "command", reason: sum, args_summary: JSON.stringify(r.input ?? {}) } };
        if (t === "plan.created" || t === "approach.changed") return { ...base, type: "decision.made", payload: { action: t === "plan.created" ? "PLAN" : "REPLAN", rationale: sum, forced_by: "LOG" } };
        if (t === "verify.finding" || t === "review.issue") return { ...base, type: "finding.created", payload: { severity: "MEDIUM", category: String(r.tool ?? t).toUpperCase(), file: String((r.input as { path?: string } | null)?.path ?? ""), line_start: (r.input as { line?: number } | null)?.line ?? "", note: sum } };
        return { ...base, type: "message.sent", payload: { sender: who, recipient: "master", type: String(r.message_type ?? "STATUS"), severity: "INFO", summary: sum, message_id: base.id, correlation_id: base.id } };
      }),
    };
  }
  throw new Error("Unrecognised format. Expected DevPilot events.jsonl ({type, actor, payload}) or {time, agent, event_type}.");
}
