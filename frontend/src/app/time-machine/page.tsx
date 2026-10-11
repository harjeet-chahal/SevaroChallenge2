import type { Metadata } from "next";

import { LastSafeMomentStrip } from "@/components/neurogrid/command";
import { CoverageDebtPanel, HandoffPanel } from "@/components/neurogrid/handoff";
import { TimeMachine } from "@/components/neurogrid/time-machine";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Coverage Time Machine" };

export default function TimeMachinePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Coverage Time Machine"
        description="The next 90 minutes, computed from schedules, credentials, live signals and known arrivals. Future frames are projections, never observed facts."
      />
      <LastSafeMomentStrip timeMachineLink={false} />
      <TimeMachine />
      <div className="grid gap-6 xl:grid-cols-2">
        <HandoffPanel />
        <CoverageDebtPanel />
      </div>
    </div>
  );
}
