"use client";
import { CheckCircle2, FileArchive, FolderOpen, Lock, Upload } from "lucide-react";
import React, { useRef, useState } from "react";
import { Badge, Button, Field, inputCls, Github } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Repository } from "@/lib/types";

const GH = /^(?:https:\/\/)?(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?\/?$/;

/** Connect a repository: paste a GitHub link, upload a folder / zip, or point at a local path. */
export function RepositoryConnect({ onConnected }: { onConnected: (r: Repository) => void }) {
  const [mode, setMode] = useState<"github" | "upload" | "local">("github");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [token, setToken] = useState("");
  const [path, setPath] = useState("");
  const [repoName, setRepoName] = useState("");
  const [uploadFiles, setUploadFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<Repository | null>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const zipInputRef = useRef<HTMLInputElement>(null);

  const parsed = GH.exec(url.trim());
  const urlErr = url.trim() && !parsed ? "Use a link like https://github.com/owner/repository" : undefined;

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      let r: Repository;
      if (mode === "github") {
        const cleanBranch = branch.trim();
        if (cleanBranch.includes("@")) {
          setErr("The Branch field contains an email address. Leave it empty to use the default branch (main).");
          setBusy(false);
          return;
        }
        r = await api.repos.create({ source_type: "GIT_URL", source_ref: url.trim(), branch: cleanBranch || undefined, github_token: token || undefined });
      } else if (mode === "upload") {
        if (!uploadFiles || uploadFiles.length === 0) {
          setErr("Please select a local folder or a .zip file to upload.");
          setBusy(false);
          return;
        }
        const fd = new FormData();
        if (repoName.trim()) fd.append("name", repoName.trim());
        for (let i = 0; i < uploadFiles.length; i++) {
          const file = uploadFiles[i];
          const pathName = (file as unknown as { webkitRelativePath?: string }).webkitRelativePath || file.name;
          fd.append("files", file, pathName);
        }
        r = await api.repos.upload(fd);
      } else {
        r = await api.repos.create({ source_type: "LOCAL_PATH", source_ref: path.trim() });
      }
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
        {([["github", "GitHub link", Github], ["upload", "Upload folder", Upload], ["local", "Local path", FolderOpen]] as const).map(([id, label, Icon]) => (
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
            <Field label="Branch (optional)" hint="Defaults to the repository's default branch"><input name="git-branch" autoComplete="off" data-1p-ignore data-lpignore="true" className={inputCls} value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" /></Field>
            <Field label="Access token (private repos / push)" hint="Used for this clone only. Never stored or logged.">
              <div className="relative"><Lock className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-fg3" aria-hidden />
                <input className={`${inputCls} pl-8`} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="optional" /></div>
            </Field>
          </div>
        </>
      ) : mode === "upload" ? (
        <div className="space-y-3">
          <Field label="Repository name (optional)" hint="Give this repository a name in DevPilot (defaults to the folder name)">
            <input className={inputCls} placeholder="my-awesome-project" value={repoName} onChange={(e) => setRepoName(e.target.value)} />
          </Field>

          {/* Hidden inputs for folder and zip */}
          <input
            type="file"
            ref={folderInputRef}
            className="hidden"
            multiple
            // @ts-expect-error webkitdirectory is standard for folder picker
            webkitdirectory="true"
            directory="true"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                setUploadFiles(e.target.files);
                if (!repoName) {
                  const firstRel = (e.target.files[0] as unknown as { webkitRelativePath?: string }).webkitRelativePath;
                  if (firstRel) setRepoName(firstRel.split("/")[0]);
                }
              }
            }}
          />
          <input
            type="file"
            ref={zipInputRef}
            className="hidden"
            accept=".zip"
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) {
                setUploadFiles(e.target.files);
                if (!repoName) setRepoName(e.target.files[0].name.replace(/\.zip$/i, ""));
              }
            }}
          />

          <div className="rounded-lg border border-dashed border-line-strong p-4 text-center">
            <div className="flex flex-col items-center justify-center gap-2">
              <Upload className="h-6 w-6 text-fg3" aria-hidden />
              <div className="text-sm font-medium text-fg">
                {uploadFiles && uploadFiles.length > 0
                  ? `Selected: ${uploadFiles.length} file(s) ready`
                  : "Upload a project folder or a .zip archive"}
              </div>
              <p className="text-xs text-fg3">
                Uploads are copied into DevPilot&apos;s workspace and initialized as an isolated repository.
              </p>
              <div className="mt-2 flex gap-2">
                <Button type="button" variant="secondary" onClick={() => folderInputRef.current?.click()}>
                  <FolderOpen className="mr-1.5 h-4 w-4" aria-hidden /> Choose Folder
                </Button>
                <Button type="button" variant="secondary" onClick={() => zipInputRef.current?.click()}>
                  <FileArchive className="mr-1.5 h-4 w-4" aria-hidden /> Choose .zip File
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <Field label="Absolute path to a project folder" hint="The folder is copied; secrets (.env, keys) are excluded. Your original changes only after you approve.">
          <input className={inputCls} placeholder="/Users/you/projects/my-app" value={path} onChange={(e) => { setPath(e.target.value); setErr(null); }} spellCheck={false} />
        </Field>
      )}
      {err && <p role="alert" className="rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
      <Button type="submit" variant="primary" loading={busy} disabled={mode === "github" ? !parsed : mode === "upload" ? !uploadFiles : !path.trim()}>
        {busy ? "Uploading & Connecting…" : mode === "upload" ? "Upload and connect" : "Connect repository"}
      </Button>
    </form>
  );
}
