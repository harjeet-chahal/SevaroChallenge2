import type { Metadata } from "next";
import { Suspense } from "react";

import { RescueSimulator } from "@/components/neurogrid/simulator";
import { PageHeader } from "@/components/shared/page-header";
import { SimulationStatus } from "@/components/status/simulation-status";

export const metadata: Metadata = { title: "Rescue Simulator" };

export default function SimulatorPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Decide · Simulate"
        title="Rescue Impact Simulator"
        description="Compare interventions before anyone is contacted. Projections only — nothing changes until a clinical lead approves a rescue contract."
      />
      <SimulationStatus />
      <Suspense>
        <RescueSimulator />
      </Suspense>
    </div>
  );
}
