"use client";
import { FileUp, Pause, Play, SkipForward } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardHeader } from "@/components/ui";
import { parseRunLog } from "@/lib/runlog";
import type { DevEvent } from "@/lib/types";
import { ActivityFeed } from "../workspace/ActivityFeed";
import { MissionTimeline } from "../workspace/Timeline";
import { AgentGuild } from "./AgentGuild";

/** Load a saved run log (e.g. eval/results/<scenario>/events.jsonl) and replay it. Clearly labelled: never presented as live. */
export function ImportRunLog() {
  const toast = useToast();
  const [events, setEvents] = useState<DevEvent[] | null>(null);
  const [name, setName] = useState("");
  const [fmt, setFmt] = useState("");
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(8);
  const [agent, setAgent] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!playing || !events) return;
    const t = setInterval(() => setI((v) => { if (v >= events.length) { setPlaying(false); return v; } return v + 1; }), 1000 / speed);
    return () => clearInterval(t);
  }, [playing, events, speed]);

  async function load(f: File | undefined) {
    if (!f) return;
    try {
      if (f.size > 20_000_000) throw new Error("File is larger than 20 MB.");
      const r = parseRunLog(await f.text());
      setEvents(r.events); setName(f.name); setFmt(r.format); setI(r.events.length); setPlaying(false); setAgent(null);
      toast("success", `Loaded ${r.events.length} events (${r.format} format). This is a replay, not a live run.`);
    } catch (e) { toast("error", (e as Error).message); }
    if (input.current) input.current.value = "";
  }
  const shown = events ? events.slice(0, i) : [];
  return (
    <Card id="import">
      <CardHeader title="Import a run log" sub="Replay a saved events.jsonl (DevPilot or prototype format). Nothing is uploaded; it is parsed in your browser."
        right={<><input ref={input} type="file" accept=".jsonl,.json,.ndjson,text/plain" className="sr-only" id="runlog" onChange={(e) => void load(e.target.files?.[0])} aria-label="Run log file" />
          <label htmlFor="runlog" className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-line-strong bg-surface px-3 text-sm hover:bg-hover"><FileUp className="h-4 w-4" aria-hidden />Choose file</label></>} />
      {!events ? <p className="px-4 py-6 text-sm text-fg3">Try <code className="font-mono">eval/results/sc-3-failing-test/events.jsonl</code>: it shows a real failing test, a repair, and the verifier passing.</p> : (
        <div className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2"><Badge tone="warning">Replay: not live</Badge><Badge>{name}</Badge><Badge>{fmt}</Badge>
            <Button size="sm" onClick={() => { if (i >= events.length) setI(0); setPlaying(!playing); }} aria-label={playing ? "Pause" : "Play"}>{playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}</Button>
            <Button size="sm" variant="ghost" onClick={() => setI(Math.min(events.length, i + 1))} aria-label="Next event"><SkipForward className="h-3.5 w-3.5" /></Button>
            <input type="range" min={0} max={events.length} value={i} onChange={(e) => { setPlaying(false); setI(Number(e.target.value)); }} aria-label="Replay position" aria-valuetext={`Event ${i} of ${events.length}`} className="min-w-[120px] flex-1" />
            <select aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="rounded border border-line-strong bg-canvas px-1 py-1 text-xs">{[1, 4, 8, 32].map((s) => <option key={s} value={s}>{s}×</option>)}</select>
            <span className="text-xs text-fg3">{i}/{events.length}</span></div>
          <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
            <div className="glass-flat max-h-[420px] overflow-y-auto rounded-lg"><ActivityFeed missionId="" events={shown} messages={[]} toolCalls={[]} loading={false} filterAgent={agent} onFilterAgent={setAgent} /></div>
            <div className="space-y-3"><AgentGuild detail={null} events={shown} live={false} selected={agent} onSelect={setAgent} /><div className="glass-flat max-h-52 overflow-y-auto rounded-lg"><MissionTimeline events={shown} /></div></div>
          </div>
        </div>)}
    </Card>
  );
}
