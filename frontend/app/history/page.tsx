import { ImportRunLog } from "@/features/cosmic/ImportRunLog";
import { MissionList } from "@/features/missions/MissionList";

export default function Page() {
  return (
    <>
      <div className="mx-auto max-w-5xl px-4 pt-4 sm:px-6 sm:pt-6"><ImportRunLog /></div>
      <MissionList terminalOnly title="Execution history" />
    </>
  );
}
