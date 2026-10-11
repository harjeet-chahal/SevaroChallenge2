import type { Metadata } from "next";

import { ChaosLab, EvaluationPanel } from "@/components/neurogrid/chaos";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Chaos Lab" };

export default function ChaosPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Chaos Lab"
        description="Inject surges, losses, contradictory signals, bad data and workflow races into isolated branches and watch the real engines respond. The baseline is never touched."
      />
      <ChaosLab />
      <EvaluationPanel />
    </div>
  );
}
