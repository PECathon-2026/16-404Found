"use client";
import { ArrowLeft, ArrowRight, FlaskConical, GitBranch, Play, ShieldAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import React, { useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorCard, Field, Skeleton, cx, inputCls, textareaCls, Github } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { ModelsConfig, Repository, Scenario } from "@/lib/types";
import { useApi } from "@/lib/useApi";
import { RepositoryConnect } from "../repositories/RepositoryConnect";

const STEPS = ["Repository", "Mission", "Limits & safety", "Review"] as const;

export function MissionCreationWizard() {
  const router = useRouter();
  const [source, setSource] = useState<"repo" | "demo">("repo");
  const [step, setStep] = useState(0);
  const [repo, setRepo] = useState<Repository | null>(null);
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [maxTokens, setMaxTokens] = useState(400000);
  const [blockPre, setBlockPre] = useState(false);
  const [allowPreFail, setAllowPreFail] = useState(false);
  const [scenario, setScenario] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const { data: repos, error: rerr, loading: rl, reload } = useApi<Repository[]>(() => api.repos.list(), []);
  const { data: cfg } = useApi<ModelsConfig>(() => api.config(), []);
  const { data: sc } = useApi(() => api.demo.scenarios(), []);
  const live = cfg?.live_available ?? false;

  async function submitLive() {
    if (!repo) return;
    setBusy(true); setErr(null);
    try {
      const m = await api.missions.create({ title: title.trim(), prompt: prompt.trim(), repository_id: repo.id, start: true,
        config: { limits: { max_tokens: maxTokens }, block_on_pre_existing: blockPre, allow_preexisting_failures: allowPreFail } });
      router.push(`/missions/${m.id}`);
    } catch (e) { setErr(e as ApiError); setBusy(false); }
  }
  async function submitDemo() {
    if (!scenario) return;
    setBusy(true); setErr(null);
    try { const m = await api.demo.create(scenario); router.push(`/missions/${m.id}`); } catch (e) { setErr(e as ApiError); setBusy(false); }
  }

  const canNext = [!!repo, title.trim().length >= 3 && prompt.trim().length >= 10, true, true][step];

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div><h1 className="text-xl font-semibold">New mission</h1><p className="text-sm text-fg3">Describe the change in plain language. DevPilot plans it, implements it in an isolated copy, tests it, reviews it, and asks you before anything is applied.</p></div>
      <div role="tablist" aria-label="Mission source" className="inline-flex rounded-md border border-line-strong p-0.5">
        <button role="tab" aria-selected={source === "repo"} onClick={() => setSource("repo")} className={cx("rounded px-3 py-1.5 text-sm", source === "repo" ? "bg-hover" : "text-fg3")}>My repository</button>
        <button role="tab" aria-selected={source === "demo"} onClick={() => setSource("demo")} className={cx("flex items-center gap-1.5 rounded px-3 py-1.5 text-sm", source === "demo" ? "bg-hover" : "text-fg3")}><FlaskConical className="h-3.5 w-3.5" aria-hidden />Demo scenario</button>
      </div>

      {source === "demo" ? (
        <Card className="space-y-3 p-4">
          <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-fg2"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
            <span>Demo missions replay a <b>scripted model</b> so you can watch the whole workflow without an API key. Planning input is scripted; the tools, test runs, verifier, security scan, completion gate and approval are real and run on a fixture repository.</span></div>
          {!sc ? <Skeleton className="h-24" /> : sc.scenarios.length === 0 ? <EmptyState title="No demo scenarios found" /> : (
            <fieldset className="min-w-0 space-y-2"><legend className="sr-only">Scenario</legend>
              {sc.scenarios.map((s: Scenario) => (
                <label key={s.id} className={cx("flex cursor-pointer gap-3 rounded-lg border p-3", scenario === s.id ? "border-accent bg-accent/5" : "border-line hover:bg-hover")}>
                  <input type="radio" name="scenario" className="mt-1" checked={scenario === s.id} onChange={() => setScenario(s.id)} />
                  <span><span className="flex items-center gap-2 text-sm font-medium">{s.title}<Badge>{s.category}</Badge></span><span className="block text-xs text-fg3">{s.description}</span><span className="mt-1 block text-xs text-fg2">“{s.prompt}”</span></span>
                </label>))}
            </fieldset>)}
          {err && <ErrorCard message={err.message} />}
          <Button variant="primary" onClick={submitDemo} loading={busy} disabled={!scenario}><Play className="h-4 w-4" aria-hidden />Run demo mission</Button>
        </Card>
      ) : (
        <>
          {!live && cfg && (
            <div role="alert" className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-fg2"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              <span><b>No model provider is configured</b>, so a mission on your own repository can’t run yet. Set <code className="font-mono">ANTHROPIC_API_KEY</code> + <code className="font-mono">ANTHROPIC_MODEL</code> (or <code className="font-mono">OPENAI_API_KEY</code> + <code className="font-mono">OPENAI_MODEL</code>) in <code className="font-mono">backend/.env</code> and restart the backend. You can still connect a repository now, or try a demo scenario.</span></div>)}
          <ol aria-label="Steps" className="flex gap-1 text-xs">{STEPS.map((s, i) => (
            <li key={s} aria-current={i === step ? "step" : undefined} className={cx("flex-1 rounded px-2 py-1.5 text-center", i === step ? "bg-accent text-accent-fg" : i < step ? "bg-hover text-fg" : "bg-surface text-fg3")}>{i + 1}. {s}</li>))}</ol>
          <Card className="space-y-4 p-4">
            {step === 0 && (
              <div className="space-y-4">
                <div><h2 className="mb-2 text-sm font-semibold">Choose a repository</h2>
                  {rl ? <Skeleton className="h-16" /> : rerr ? <ErrorCard message={rerr.message} onRetry={reload} /> : (repos ?? []).length === 0 ? <p className="text-sm text-fg3">No repositories yet. Connect one below.</p> : (
                    <fieldset className="min-w-0 space-y-1.5"><legend className="sr-only">Repositories</legend>
                      {(repos ?? []).map((r) => (
                        <label key={r.id} className={cx("flex cursor-pointer items-center gap-3 rounded-lg border p-2.5", repo?.id === r.id ? "border-accent bg-accent/5" : "border-line hover:bg-hover")}>
                          <input type="radio" name="repo" checked={repo?.id === r.id} onChange={() => setRepo(r)} />
                          {r.source_type === "GIT_URL" ? <Github className="h-4 w-4 text-fg3" aria-hidden /> : <GitBranch className="h-4 w-4 text-fg3" aria-hidden />}
                          <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{r.github_owner ? `${r.github_owner}/${r.github_name}` : r.name}</span><span className="block truncate text-xs text-fg3">{r.source_ref}</span></span>
                          <Badge>{r.detected_commands?.test?.runner ?? "no tests"}</Badge></label>))}
                    </fieldset>)}
                </div>
                <div className="border-t border-line pt-4"><h2 className="mb-2 text-sm font-semibold">Or connect a new one</h2><RepositoryConnect onConnected={(r) => { setRepo(r); reload(); }} /></div>
              </div>)}
            {step === 1 && (
              <div className="space-y-3">
                <Field label="Title"><input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Add JWT authentication" maxLength={120} /></Field>
                <Field label="What should DevPilot do?" hint="Be specific about behaviour. If something is ambiguous, DevPilot will ask you instead of guessing.">
                  <textarea className={textareaCls} rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Implement JWT authentication in my FastAPI project, add login and registration endpoints, write unit tests, and ensure secure token handling." /></Field>
              </div>)}
            {step === 2 && (
              <div className="space-y-4">
                <div className="rounded-md border border-line p-3 text-sm"><b>Always on:</b> work happens in an isolated copy · commands are allowlisted · existing tests are protected · no network · nothing is applied without your approval.</div>
                <Field label="Token budget" hint="The mission escalates to you when this is reached."><input type="number" min={20000} step={10000} className={inputCls} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} /></Field>
                <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={blockPre} onChange={(e) => setBlockPre(e.target.checked)} /><span><b>Also block on security findings in files I didn’t change</b><span className="block text-xs text-fg3">Off by default so old issues in a large repository don’t block unrelated work. They are still reported.</span></span></label>
                <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={allowPreFail} onChange={(e) => setAllowPreFail(e.target.checked)} /><span><b>Tolerate tests that were already failing before the change</b><span className="block text-xs text-fg3">New failures still block. Use this when the repository’s test suite is already red.</span></span></label>
              </div>)}
            {step === 3 && (
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <div><dt className="text-xs text-fg3">Repository</dt><dd>{repo?.github_owner ? `${repo.github_owner}/${repo.github_name}` : repo?.name}</dd></div>
                <div><dt className="text-xs text-fg3">Model</dt><dd>{live ? "live provider" : "none configured"}</dd></div>
                <div className="sm:col-span-2"><dt className="text-xs text-fg3">Title</dt><dd>{title}</dd></div>
                <div className="sm:col-span-2"><dt className="text-xs text-fg3">Request</dt><dd className="whitespace-pre-wrap">{prompt}</dd></div>
                <div><dt className="text-xs text-fg3">Token budget</dt><dd>{maxTokens.toLocaleString()}</dd></div>
                <div><dt className="text-xs text-fg3">Block on untouched-file findings</dt><dd>{blockPre ? "yes" : "no"} · tolerate pre-existing failing tests: {allowPreFail ? "yes" : "no"}</dd></div>
              </dl>)}
            {err && <ErrorCard message={err.message} />}
            <div className="flex items-center justify-between border-t border-line pt-3">
              <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}><ArrowLeft className="h-4 w-4" aria-hidden />Back</Button>
              {step < 3 ? <Button variant="primary" onClick={() => setStep((s) => s + 1)} disabled={!canNext}>Next<ArrowRight className="h-4 w-4" aria-hidden /></Button>
                : <Button variant="primary" onClick={submitLive} loading={busy} disabled={!live}><Play className="h-4 w-4" aria-hidden />{live ? "Start mission" : "Needs a model provider"}</Button>}
            </div>
          </Card>
        </>)}
    </div>
  );
}
