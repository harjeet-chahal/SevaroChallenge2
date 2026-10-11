import type { Metadata } from "next";

import { ContractAudit, ContractVerificationPanel } from "@/components/neurogrid/contracts";
import { OptimizationProvider } from "@/components/optimization/optimization-provider";
import { PageHeader } from "@/components/shared/page-header";
import { AnalysisProvider } from "@/components/state/analysis-provider";
import { OperationalStateProvider } from "@/components/state/operational-state-provider";
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
                title="Rescue Contracts"
                description="Each rescue moves through a fixed lifecycle. Accepted is not active: a contract is verified only after the physician is online and the gap is re-measured."
              />
              <ContractVerificationPanel />
              <ContractAudit />
              <InterventionBoard />
              <InterventionComposer />
            </div>
          </WorkflowProvider>
        </OptimizationProvider>
      </AnalysisProvider>
    </OperationalStateProvider>
  );
}
