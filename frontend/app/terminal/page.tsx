"use client";
import { Card } from "@/components/ui";
import { TerminalPanel } from "@/features/cosmic/DevPanels";
import { MissionScope } from "@/features/cosmic/MissionScope";

export default function Page() {
  return (
    <MissionScope title="Terminal" subtitle="Every command the agents ran in the sandbox, with exit codes and real output. Read-only: the sandbox allowlist is never bypassed.">
      {(live, id) => <Card className="h-[70vh] min-h-[360px] overflow-hidden"><TerminalPanel missionId={id} toolCalls={live.toolCalls} /></Card>}
    </MissionScope>
  );
}
