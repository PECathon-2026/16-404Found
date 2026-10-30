"use client";
import { ChevronRight, FileCode2, FileText, Folder, FolderOpen, GitBranch, RefreshCw } from "lucide-react";
import React, { useMemo, useState } from "react";
import { Badge, EmptyState, ErrorCard, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useApi } from "@/lib/useApi";

interface Node { name: string; path: string; dir: boolean; change: string | null; children: Node[] }
function build(files: { path: string; change: string | null }[]): Node[] {
  const root: Node = { name: "", path: "", dir: true, change: null, children: [] };
  for (const f of files) {
    let cur = root;
    f.path.split("/").forEach((part, i, arr) => {
      const last = i === arr.length - 1;
      let n = cur.children.find((c) => c.name === part && c.dir === !last);
      if (!n) { n = { name: part, path: arr.slice(0, i + 1).join("/"), dir: !last, change: last ? f.change : null, children: [] }; cur.children.push(n); }
      if (f.change && !last) n.change = n.change ?? "MODIFY";
      cur = n;
    });
  }
  const sort = (ns: Node[]) => { ns.sort((a, b) => Number(b.dir) - Number(a.dir) || a.name.localeCompare(b.name)); ns.forEach((n) => sort(n.children)); };
  sort(root.children);
  return root.children;
}
const isCode = (n: string) => /\.(py|ts|tsx|js|jsx|go|rs|java|rb)$/.test(n);
const CH: Record<string, string> = { MODIFY: "bg-warning", ADD: "bg-success", DELETE: "bg-danger" };

function Row({ n, depth, sel, onSelect, openAll }: { n: Node; depth: number; sel: string | null; onSelect: (p: string) => void; openAll: boolean }) {
  const [open, setOpen] = useState(openAll || n.change !== null || depth < 1);
  const icon = n.dir ? (open ? <FolderOpen className="h-3.5 w-3.5 shrink-0 text-cyan" aria-hidden /> : <Folder className="h-3.5 w-3.5 shrink-0 text-cyan" aria-hidden />)
    : isCode(n.name) ? <FileCode2 className="h-3.5 w-3.5 shrink-0 text-fg2" aria-hidden /> : <FileText className="h-3.5 w-3.5 shrink-0 text-fg2" aria-hidden />;
  return (
    <li>
      <button onClick={() => (n.dir ? setOpen(!open) : onSelect(n.path))} aria-expanded={n.dir ? open : undefined} aria-current={sel === n.path ? "true" : undefined}
        className={cx("flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[13px] hover:bg-hover", sel === n.path && "bg-accent/20 text-fg")} style={{ paddingLeft: 6 + depth * 14 }}>
        {n.dir ? <ChevronRight className={cx("h-3 w-3 shrink-0 text-fg3 transition-transform", open && "rotate-90")} aria-hidden /> : <span className="w-3" />}
        {icon}<span className="min-w-0 flex-1 truncate font-mono">{n.name}</span>
        {n.change && <span className={cx("h-2 w-2 shrink-0 rounded-full", CH[n.change] ?? "bg-neutral")} title={`${n.change.toLowerCase()} by this mission`} />}
      </button>
      {n.dir && open && <ul>{n.children.map((c) => <Row key={c.path} n={c} depth={depth + 1} sel={sel} onSelect={onSelect} openAll={openAll} />)}</ul>}
    </li>
  );
}

/** Real file tree of the isolated workspace; modified/added files carry a dot. Nothing here is fabricated. */
export function RepoExplorer({ missionId, repoName, selected, onSelect, version }: { missionId: string | null; repoName?: string; selected: string | null; onSelect: (p: string) => void; version: string }) {
  const { data, error, loading, reload } = useApi(async () => (missionId ? api.missions.files(missionId) : null), [missionId, version]);
  const tree = useMemo(() => build(data?.files ?? []), [data]);
  const changed = (data?.files ?? []).filter((f) => f.change).length;
  return (
    <div className="flex h-full min-h-[240px] flex-col">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2"><span className="text-sm font-semibold">Repository</span>
        <Badge icon={<GitBranch className="h-3 w-3" />} className="ml-auto">{data?.branch ?? "workspace"}</Badge>
        <button onClick={reload} aria-label="Refresh file tree" className="rounded p-1 text-fg3 hover:bg-hover hover:text-fg"><RefreshCw className="h-3.5 w-3.5" /></button></div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {!missionId ? <EmptyState title="No workspace" description="A mission creates an isolated copy of the repository to explore." />
          : error ? <ErrorCard message={error.message} onRetry={reload} /> : loading && !data ? <div className="space-y-1.5">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-5" />)}</div>
          : tree.length === 0 ? <EmptyState title="No files yet" description="The workspace is created when the mission starts." />
          : <><p className="px-1.5 pb-1 font-mono text-xs text-fg3">{repoName}</p><ul role="tree" aria-label="Repository files">{tree.map((n) => <Row key={n.path} n={n} depth={0} sel={selected} onSelect={onSelect} openAll={false} />)}</ul></>}
      </div>
      {missionId && <div className="border-t border-line px-3 py-1.5 text-[11px] text-fg3">{changed} changed file{changed === 1 ? "" : "s"} · dots mark files this mission touched</div>}
    </div>
  );
}
