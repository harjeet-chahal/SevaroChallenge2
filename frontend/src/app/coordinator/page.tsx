import type { Metadata } from "next";

import { CommandTabs, DatasetButton, DatasetLoaderWhenEmpty } from "@/components/coordinator/command-tabs";
import { CoordinatorSummaryCards } from "@/components/coordinator/summary-cards";
import {
  AvailabilityBoard,
  LastSafeMomentStrip,
  PriorityOne,
  ProblemBoard,
} from "@/components/neurogrid/command";
import { OptimizationProvider } from "@/components/optimization/optimization-provider";
import { PageHeader } from "@/components/shared/page-header";
import { AnalysisProvider } from "@/components/state/analysis-provider";
import { OperationalStateProvider } from "@/components/state/operational-state-provider";
import { WorkflowProvider } from "@/components/workflow/workflow-provider";

export const metadata: Metadata = { title: "Command Center" };

export default function CoordinatorPage() {
  return (
    <OperationalStateProvider>
      <AnalysisProvider>
        <OptimizationProvider>
          <WorkflowProvider role="coordinator">
            <div className="flex flex-col gap-[22px]">
              <PageHeader
                title="Command Center"
                description="The single most urgent problem first, then every hospital's last safe moment to act. Every figure comes from the backend engines on the simulation clock."
                actions={<DatasetButton />}
              />
              <DatasetLoaderWhenEmpty />
              <PriorityOne />
              <CoordinatorSummaryCards />
              <LastSafeMomentStrip />
              <div className="grid grid-cols-1 items-start gap-4 min-[900px]:grid-cols-3">
                <ProblemBoard className="min-[900px]:col-span-2" />
                <AvailabilityBoard />
              </div>
              <CommandTabs />
            </div>
          </WorkflowProvider>
        </OptimizationProvider>
      </AnalysisProvider>
    </OperationalStateProvider>
  );
}
