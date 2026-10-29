export type MissionStatus = "CREATED" | "PLANNING" | "EXECUTING" | "VERIFYING" | "AWAITING_HUMAN" | "AWAITING_APPROVAL" | "PAUSED" | "COMPLETED" | "REJECTED" | "FAILED" | "CANCELLED";
export const TERMINAL: MissionStatus[] = ["COMPLETED", "REJECTED", "FAILED", "CANCELLED"];
export type Severity = "INFO" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AgentId = "master" | "planner" | "developer" | "tester" | "security" | "verifier";

export interface Repository {
  id: string; name: string; source_type: "LOCAL_PATH" | "GIT_URL"; source_ref: string; default_branch: string | null;
  language_hints: Record<string, number> | null; head_commit: string | null; github_owner: string | null; github_name: string | null;
  detected_commands: { test?: { runner: string } | null; lint?: { runner: string } | null; build?: { runner: string } | null } | null; created_at: string;
}
export interface Criterion { id: string; text: string; verification_method: string; verification: Record<string, unknown>; status: "UNVERIFIED" | "PASS" | "FAIL" | "INCONCLUSIVE"; evidence_refs: unknown[] }
export interface HumanRequest { id: string; kind: "CLARIFICATION" | "ESCALATION"; question: string; options: { id: string; label: string; needs_text?: boolean }[]; evidence_refs: EvidenceRef[]; status: string }
export interface Gate { clear: boolean; reasons: string[]; needs_ack: string[]; notes: string[] }
export interface AgentRow { agent_id: AgentId; status: string; current_task_id: string | null; executions: number; last_error?: string }
export interface MissionDetail {
  id: string; title: string; request: string; status: MissionStatus; status_reason: string | null; mode: "live" | "scripted";
  repository: Repository | null; base_commit: string | null; objectives: string[]; risks: string[]; acceptance_criteria: Criterion[]; criteria_version: number;
  counters: { steps: number; repair_cycles: number; replans: number }; budgets: { tokens: { limit: number; used: number } };
  agents: AgentRow[]; pending_human_request: HumanRequest | null; gate: Gate | null; current_patch_sha256: string | null;
  sandbox_mode: string; outcome: Outcome | null; config: Record<string, unknown>; created_at: string; updated_at: string;
}
export interface MissionSummary {
  id: string; title: string; status: MissionStatus; status_reason: string | null; mode: string; repository: { id: string; name: string | null; source_type: string | null };
  counters: { steps: number; repair_cycles: number; replans: number }; tokens_used: number; created_at: string; updated_at: string; pending_action: string | null;
}
export interface EvidenceRef { kind: string; id: string; locator?: string }
export interface Task {
  id: string; key: string; kind: string; title: string; description: string; status: string; assignee: string | null; retries: number;
  criteria_refs: string[]; files_hint: string[]; depends_on: string[]; failure_context: Record<string, unknown> | null; started_at: string | null; finished_at: string | null;
}
export interface Msg { id: string; sender: string; recipient: string; type: string; severity: Severity; payload: Record<string, unknown>; evidence_refs: EvidenceRef[]; correlation_id: string; created_at: string; task_id: string | null }
export interface Decision { id: string; step: number; action: string; rationale: string; forced_by: string; target_task_id: string | null; target_agent: string | null; evidence_refs: EvidenceRef[]; created_at: string }
export interface ToolCallRow { id: string; agent_id: string; tool: string; args: Record<string, unknown>; status: string; exit_code: number | null; duration_ms: number | null; output_excerpt: string | null; redactions: number | null; policy_reason: string | null; started_at: string; task_id: string | null }
export interface TestFailure { test_id: string; class: string; message: string; trace_excerpt?: string; suspected_files?: string[] }
export interface TestRun { id: string; kind: string; runner: string; command: string; patch_sha256: string | null; total: number; passed: number; failed: number; errored: number; skipped: number; duration_s: number; outcome: string; failures: TestFailure[]; created_at: string }
export interface Finding { id: string; severity: Severity; category: string; cwe: string | null; file: string | null; line_start: number | null; evidence: string; recommendation: string; confidence: number; status: string; source: string; raised_by: string; waive_reason: string | null; created_at: string }
export interface DiffFile { path: string; change_type: string; additions: number; deletions: number; is_test_file: boolean; tamper_flags: string[]; original: string | null; modified: string | null; unified: string }
export interface Diffs { patch_sha256: string | null; files: DiffFile[] }
export interface VerificationResult { ac_id: string; status: string; method: string; evidence: Record<string, unknown>; confidence: number }
export interface Verification { id: string; patch_sha256: string; overall: string; results: VerificationResult[]; regression_check: { new_failures?: string[]; fixed?: string[]; baseline_failures?: string[]; command?: string } | null; tamper_check: { modified_existing_tests?: string[] } | null }
export interface OutcomeItem { id: string; text: string; source?: string; status?: string; note?: string; why?: string }
export interface Outcome { terminal_status: string; reason: string | null; mode: string; patch_sha256: string | null; baseline: { outcome: string; total: number; passed: number; failed: number } | null; final_tests: { outcome: string; total: number; passed: number; failed: number } | null;
  verified: OutcomeItem[]; unresolved: OutcomeItem[]; unverified_agent_claims: OutcomeItem[]; model_claims: OutcomeItem[]; notes: string[]; repair_cycles: number; steps: number; tokens_used: number;
  applied?: { branch?: string; base_branch?: string; commit?: string; pushed?: boolean; pr_url?: string; push_error?: string; error?: string; applied_to?: string } }
export interface Metrics { tokens_used: number; model_calls: number; tool_calls: number; tool_denied: number; tool_errors: number; developer_tool_calls: number; redundant_tool_call_rate: number | null;
  distinct_developer_tools: number; repair_cycles: number; messages: number; test_runs: number; final_test_outcome: string | null; findings: { total: number; open: number }; cost_usd: number | null; cost_note: string }
export interface DevEvent { id: string; type: string; actor: string; task_id: string | null; created_at: string; payload: Record<string, unknown> }
export interface ModelsConfig { providers: { id: string; available: boolean; reason: string | null }[]; models: Record<string, string | null>; live_available: boolean; sandbox_mode: string; sandbox_note: string; github_token_configured: boolean }
export interface EvalCheck { name: string; ok: boolean; detail: string }
export interface EvalResult { id: string; title: string; ok: boolean; checks: EvalCheck[]; seconds: number; mission_id: string; final_status: string; error: string | null }
export interface Scenario { id: string; title: string; prompt: string; category: string; description: string; scripted: boolean }
