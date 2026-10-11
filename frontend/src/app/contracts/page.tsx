import type { Metadata } from "next";

import { ContractAudit, ContractVerificationPanel } from "@/components/neurogrid/contracts";
import { OptimizationProvider } from "@/components/optimization/optimization-provider";
import { PageHeader } from "@/components/shared/page-header";
import { AnalysisProvider } from "@/components/state/analysis-provider";
import { OperationalStateProvider } from "@/components/state/operational-state-provider";
import { SimulationStatus } from "@/components/status/simulation-status";
import { InterventionBoard } from "@/components/workflow/intervention-board";
import { InterventionComposer } from "@/components/workflow/intervention-composer";
import { WorkflowProvider } from "@/components/workflow/workflow-provider";

export const metadata: Metadata = { title: "Rescue Contracts" };

export default function ContractsPage() {
  return (
    <OperationalStateProvider>
      <AnalysisProvider>
        <OptimizationProvider>
          <WorkflowProvider role="coordinator">
            <div className="space-y-6">
              <PageHeader
                eyebrow="Approve · Act · Verify"
                title="Rescue Contracts"
                description="Every rescue is an auditable contract: proposal, clinical-lead approval (re-validated against fresh state), simulated offers, responses, activation and verified recovery."
              />
              <SimulationStatus />
              <ContractVerificationPanel />
              <InterventionBoard />
              <InterventionComposer />
              <ContractAudit />
            </div>
          </WorkflowProvider>
        </OptimizationProvider>
      </AnalysisProvider>
    </OperationalStateProvider>
  );
}
