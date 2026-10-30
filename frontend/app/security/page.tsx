"use client";
import { ShieldCheck, ShieldX } from "lucide-react";
import { Badge, Card, CardHeader } from "@/components/ui";
import { MissionScope } from "@/features/cosmic/MissionScope";
import { SecurityPanel, VerificationSummary } from "@/features/workspace/panels";

export default function Page() {
  return (
    <MissionScope title="Security" subtitle="Secrets, injection risks, unsafe operations and prompt-injection text, each with file, line and evidence. Secrets are masked everywhere.">
      {(live, id) => {
        const open = live.findings.filter((f) => ["OPEN", "DISPUTED", "FIX_PROPOSED"].includes(f.status));
        const blockers = open.filter((f) => f.severity === "HIGH" || f.severity === "CRITICAL");
        return (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2"><Badge tone={blockers.length ? "danger" : "success"} icon={blockers.length ? <ShieldX className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}>{blockers.length ? `${blockers.length} blocking finding(s)` : "nothing blocking approval"}</Badge>
              <Badge>{open.length} open</Badge><Badge tone="success">{live.findings.filter((f) => f.status === "RESOLVED").length} resolved by re-scan</Badge></div>
            <Card><CardHeader title="Findings" /><SecurityPanel missionId={id} findings={live.findings} loading={live.loading} onChanged={() => void live.refresh()} /></Card>
            <Card><CardHeader title="Independent verification" /><div className="p-4"><VerificationSummary v={live.verification} /></div></Card>
          </div>);
      }}
    </MissionScope>
  );
}
