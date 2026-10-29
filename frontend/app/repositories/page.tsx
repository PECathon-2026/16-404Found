"use client";
import { GitBranch } from "lucide-react";
import Link from "next/link";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorCard, Mono, Skeleton, Github } from "@/components/ui";
import { RepositoryConnect } from "@/features/repositories/RepositoryConnect";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Repository } from "@/lib/types";
import { useApi } from "@/lib/useApi";

export default function Page() {
  const { data, error, loading, reload } = useApi<Repository[]>(() => api.repos.list(), []);
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
      <div><h1 className="text-xl font-semibold">Repositories</h1><p className="text-sm text-fg3">Connect a GitHub link or a local folder. DevPilot always works on a private copy.</p></div>
      <Card><CardHeader title="Connect a repository" /><div className="p-4"><RepositoryConnect onConnected={() => reload()} /></div></Card>
      <Card><CardHeader title="Connected" />
        {error ? <div className="p-4"><ErrorCard message={error.message} onRetry={reload} /></div> : loading ? <Skeleton className="m-4 h-16" /> : (data ?? []).length === 0 ? <EmptyState title="No repositories yet" description="Paste a GitHub link above to start." /> : (
          <ul className="divide-y divide-line">{(data ?? []).map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              {r.source_type === "GIT_URL" ? <Github className="h-4 w-4 text-fg3" aria-hidden /> : <GitBranch className="h-4 w-4 text-fg3" aria-hidden />}
              <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{r.github_owner ? `${r.github_owner}/${r.github_name}` : r.name}</div><div className="truncate text-xs text-fg3"><Mono>{r.source_ref}</Mono> · {r.default_branch ?? "no git"}{r.head_commit ? ` @ ${r.head_commit.slice(0, 7)}` : ""} · {timeAgo(r.created_at)}</div></div>
              {Object.keys(r.language_hints ?? {}).slice(0, 3).map((l) => <Badge key={l}>{l}</Badge>)}<Badge tone={r.detected_commands?.test ? "success" : "neutral"}>{r.detected_commands?.test ? `tests: ${r.detected_commands.test.runner}` : "no tests detected"}</Badge>
              <Link href={`/missions/new`}><Button size="sm">New mission</Button></Link></li>))}</ul>)}</Card>
    </div>
  );
}
