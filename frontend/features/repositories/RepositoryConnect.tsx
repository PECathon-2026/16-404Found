"use client";
import { CheckCircle2, FolderOpen, Lock } from "lucide-react";
import React, { useState } from "react";
import { Badge, Button, Field, inputCls, Github } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Repository } from "@/lib/types";

const GH = /^(?:https:\/\/)?(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/;

/** Connect a repository: paste a GitHub link (cloned into a DevPilot-owned copy) or point at a local folder. */
export function RepositoryConnect({ onConnected }: { onConnected: (r: Repository) => void }) {
  const [mode, setMode] = useState<"github" | "local">("github");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [token, setToken] = useState("");
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<Repository | null>(null);
  const parsed = GH.exec(url.trim());
  const urlErr = url.trim() && !parsed ? "Use a link like https://github.com/owner/repository" : undefined;

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = mode === "github"
        ? await api.repos.create({ source_type: "GIT_URL", source_ref: url.trim(), branch: branch.trim() || undefined, github_token: token || undefined })
        : await api.repos.create({ source_type: "LOCAL_PATH", source_ref: path.trim() });
      setToken(""); setDone(r); onConnected(r);
    } catch (x) { setErr((x as ApiError).message); } finally { setBusy(false); }
  }

  if (done) {
    const langs = Object.entries(done.language_hints ?? {}).sort((a, b) => b[1] - a[1]).map(([l]) => l).slice(0, 3);
    return (
      <div role="status" className="rounded-lg border border-success/30 bg-success/10 p-3 text-sm">
        <div className="flex items-center gap-2 font-medium text-success"><CheckCircle2 className="h-4 w-4" aria-hidden />Connected {done.github_owner ? `${done.github_owner}/${done.github_name}` : done.name}</div>
        <p className="mt-1 text-xs text-fg2">{langs.join(", ") || "no source languages detected"} · branch {done.default_branch ?? "n/a"} · tests: {done.detected_commands?.test?.runner ?? "none detected"}</p>
        {done.source_type === "GIT_URL" && <p className="mt-1 text-xs text-fg3">DevPilot works on its own clone. Nothing reaches GitHub unless you approve a change and tick “push”.</p>}
      </div>
    );
  }
  return (
    <form onSubmit={connect} className="space-y-3">
      <div role="tablist" aria-label="Repository source" className="inline-flex rounded-md border border-line-strong p-0.5">
        {([["github", "GitHub link", Github], ["local", "Local folder", FolderOpen]] as const).map(([id, label, Icon]) => (
          <button type="button" key={id} role="tab" aria-selected={mode === id} onClick={() => { setMode(id); setErr(null); }}
            className={`flex items-center gap-1.5 rounded px-3 py-1.5 text-sm ${mode === id ? "bg-hover text-fg" : "text-fg3"}`}><Icon className="h-3.5 w-3.5" aria-hidden />{label}</button>))}
      </div>
      {mode === "github" ? (
        <>
          <Field label="GitHub repository link" error={urlErr} hint="DevPilot clones it, plans and edits on a private copy, and shows you the patch to approve.">
            <input className={inputCls} placeholder="https://github.com/owner/repository" value={url} onChange={(e) => { setUrl(e.target.value); setErr(null); }} autoComplete="off" spellCheck={false} />
          </Field>
          {parsed && <Badge tone="success" icon={<Github className="h-3 w-3" />}>{parsed[1]}/{parsed[2].replace(/\.git$/, "")}</Badge>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Branch (optional)" hint="Defaults to the repository's default branch"><input className={inputCls} value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" /></Field>
            <Field label="Access token (private repos / push)" hint="Used for this clone only. Never stored or logged.">
              <div className="relative"><Lock className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-fg3" aria-hidden />
                <input className={`${inputCls} pl-8`} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="optional" /></div>
            </Field>
          </div>
        </>
      ) : (
        <Field label="Absolute path to a project folder" hint="The folder is copied; secrets (.env, keys) are excluded. Your original changes only after you approve.">
          <input className={inputCls} placeholder="/Users/you/projects/my-app" value={path} onChange={(e) => { setPath(e.target.value); setErr(null); }} spellCheck={false} />
        </Field>
      )}
      {err && <p role="alert" className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <Button type="submit" variant="primary" loading={busy} disabled={mode === "github" ? !parsed : !path.trim()}>{busy ? "Connecting…" : "Connect repository"}</Button>
    </form>
  );
}
