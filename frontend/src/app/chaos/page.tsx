import type { Metadata } from "next";

import { ChaosLab, EvaluationPanel } from "@/components/neurogrid/chaos";
import { PageHeader } from "@/components/shared/page-header";
import { SimulationStatus } from "@/components/status/simulation-status";

export const metadata: Metadata = { title: "Chaos Lab" };

export default function ChaosPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Resilience"
        title="Chaos Lab"
        description="Inject surges, losses, contradictory signals, bad data and workflow races into isolated branches and watch the real engines respond. The baseline is never touched."
      />
      <SimulationStatus />
      <ChaosLab />
      <EvaluationPanel />
    </div>
  );
}
