import type { Metadata } from "next";

import { AlertDetails } from "@/components/coordinator/alert-details";
import { AlertQueue } from "@/components/coordinator/alert-queue";
import { ConsultationQueue } from "@/components/coordinator/consultation-queue";
import { EventHistory } from "@/components/coordinator/event-history";
import { HospitalCoverage } from "@/components/coordinator/hospital-coverage";
import { PhysicianActivityPanel } from "@/components/coordinator/physician-activity";
import { CoordinatorSummaryCards } from "@/components/coordinator/summary-cards";
import { DatasetPanel } from "@/components/dataset/dataset-panel";
import { OptimizationProvider } from "@/components/optimization/optimization-provider";
import { RecommendationPanel } from "@/components/optimization/recommendation-panel";
import { PageHeader } from "@/components/shared/page-header";
import { AnalysisProvider } from "@/components/state/analysis-provider";
import { OperationalStateProvider } from "@/components/state/operational-state-provider";
import { SimulationStatus } from "@/components/status/simulation-status";
import { InterventionBoard } from "@/components/workflow/intervention-board";
import { InterventionComposer } from "@/components/workflow/intervention-composer";
import { WorkflowProvider } from "@/components/workflow/workflow-provider";

export const metadata: Metadata = { title: "Operations Coordinator" };

export default function CoordinatorPage() {
  return (
    <OperationalStateProvider>
      <AnalysisProvider>
        <OptimizationProvider>
          <WorkflowProvider role="coordinator">
          <div className="space-y-6">
            <PageHeader
              eyebrow="Operations Coordinator"
              title="Network operations"
              description="See what needs attention now and what is coming next, propose an intervention, and follow it through approval, offer and activation."
            />
            <SimulationStatus />
            <DatasetPanel />
            <CoordinatorSummaryCards />
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <AlertQueue className="lg:col-span-2" />
              <AlertDetails />
              <InterventionComposer className="lg:col-span-3" />
              <InterventionBoard className="lg:col-span-3" />
              <RecommendationPanel className="lg:col-span-3" />
              <HospitalCoverage className="lg:col-span-3" />
              <ConsultationQueue className="lg:col-span-2" />
              <PhysicianActivityPanel />
              <EventHistory className="lg:col-span-3" />
            </div>
          </div>
          </WorkflowProvider>
        </OptimizationProvider>
      </AnalysisProvider>
    </OperationalStateProvider>
  );
}
