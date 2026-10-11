import type { Metadata } from "next";
import { Suspense } from "react";

import { RescueSimulator } from "@/components/neurogrid/simulator";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Rescue Simulator" };

export default function SimulatorPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Rescue Simulator"
        description="Every option is replayed against an isolated copy of the network and ranked with hard rules first. Projections only — nothing changes until a clinical lead approves a rescue contract."
      />
      <Suspense>
        <RescueSimulator />
      </Suspense>
    </div>
  );
}
