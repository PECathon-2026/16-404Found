"use client";
import { useRouter } from "next/navigation";
import { Card, CardHeader } from "@/components/ui";
import { TestResultsMini } from "@/features/cosmic/DevPanels";
import { MissionScope } from "@/features/cosmic/MissionScope";
import { TestsPanel } from "@/features/workspace/panels";

export default function Page() {
  const router = useRouter();
  return (
    <MissionScope title="Tests" subtitle="System-captured runs, tied to the exact patch they tested. Developer self-checks are shown but never count as evidence.">
      {(live, id) => (
        <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
          <Card className="min-w-0"><CardHeader title="Runs" /><TestsPanel runs={live.tests} loading={live.loading} /></Card>
          <Card><CardHeader title="Latest results" /><TestResultsMini missionId={id} runs={live.tests} onViewLogs={() => router.push("/terminal")} /></Card>
        </div>)}
    </MissionScope>
  );
}
