"use client";
import { CheckCircle2, CircleSlash, ShieldAlert } from "lucide-react";
import { Badge, Card, CardHeader, ErrorCard, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { ModelsConfig } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export default function Page() {
  const { data: c, error, reload } = useApi<ModelsConfig>(() => api.config(), []);
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div><h1 className="text-xl font-semibold">Settings</h1><p className="text-sm text-fg3">Read-only. Keys and models are configured in <code className="font-mono">backend/.env</code>; the browser never sees a key.</p></div>
      {error ? <ErrorCard message={error.message} onRetry={reload} /> : !c ? <Skeleton className="h-40" /> : (
        <>
          <Card><CardHeader title="Model providers" /><ul className="divide-y divide-line">{c.providers.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-sm">{p.available ? <CheckCircle2 className="h-4 w-4 text-success" aria-hidden /> : <CircleSlash className="h-4 w-4 text-fg3" aria-hidden />}
              <b className="sm:w-32">{p.id}</b><span className="min-w-0 flex-1 basis-40 text-fg3">{p.available ? (c.models[p.id] ? `model: ${c.models[p.id]}` : "available") : p.reason}</span><Badge tone={p.available ? "success" : "neutral"}>{p.available ? "available" : "not configured"}</Badge></li>))}</ul></Card>
          <Card><CardHeader title="Sandbox" /><div className="space-y-2 p-4 text-sm"><div className="flex items-center gap-2"><Badge tone="warning" icon={<ShieldAlert className="h-3 w-3" />}>{c.sandbox_mode}</Badge></div><p className="text-fg2">{c.sandbox_note}</p>
            <ul className="list-disc space-y-0.5 pl-5 text-fg3"><li>Commands run without a shell, from an allowlist; destructive ones are blocked.</li><li>File access is confined to an isolated copy of the repository.</li><li>No network access for agents. Existing tests are protected from edits.</li></ul></div></Card>
          <Card><CardHeader title="GitHub" /><div className="p-4 text-sm"><p>Backend token: <Badge tone={c.github_token_configured ? "success" : "neutral"}>{c.github_token_configured ? "configured" : "not set"}</Badge></p>
            <p className="mt-1 text-fg3">Optional. Needed for private repositories, pushing a branch and opening pull requests. You can also supply a token per action in the UI; it is never stored.</p></div></Card>
        </>)}
    </div>
  );
}
