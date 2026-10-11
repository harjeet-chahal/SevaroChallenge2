import type { Metadata } from "next";

import { AlertDetails } from "@/components/coordinator/alert-details";
import { AlertQueue } from "@/components/coordinator/alert-queue";
import { NetworkDetail } from "@/components/coordinator/network-detail";
import { CoordinatorSummaryCards } from "@/components/coordinator/summary-cards";
import { CoordinatorToolbar } from "@/components/coordinator/toolbar";
import { SECTION_IDS } from "@/components/coordinator/section-ids";
import { CoordinatorViewProvider } from "@/components/coordinator/view-provider";
import { DatasetGate } from "@/components/dataset/dataset-gate";
import { OptimizationProvider } from "@/components/optimization/optimization-provider";
import { AnalysisProvider } from "@/components/state/analysis-provider";
import { OperationalStateProvider } from "@/components/state/operational-state-provider";
import { InterventionBoard } from "@/components/workflow/intervention-board";
import { InterventionComposer } from "@/components/workflow/intervention-composer";
import { WorkflowNoticeToast } from "@/components/workflow/notice-toast";
import { WorkflowProvider } from "@/components/workflow/workflow-provider";

export const metadata: Metadata = { title: "Command center" };

/**
 * Reading order follows the coordinator's job: the network at a glance, then what needs
 * attention and what to do about it, then what is already in motion, then supporting
 * detail one tab at a time. Proposals open in a drawer so the alert stays in view.
 */
export default function CoordinatorPage() {
  return (
    <OperationalStateProvider>
      <AnalysisProvider>
        <OptimizationProvider>
          <WorkflowProvider role="coordinator">
            <CoordinatorViewProvider>
              <div className="flex flex-col gap-[22px]">
                <CoordinatorToolbar />
                <DatasetGate />
                <CoordinatorSummaryCards />
                <div
                  id={SECTION_IDS.triage}
                  className="grid scroll-mt-28 grid-cols-1 items-start gap-[22px] lg:grid-cols-12"
                >
                  <AlertQueue className="lg:col-span-5" />
                  <AlertDetails className="lg:sticky lg:top-[96px] lg:col-span-7" />
                </div>
                <InterventionBoard />
                <NetworkDetail />
              </div>
              <InterventionComposer />
              <WorkflowNoticeToast />
            </CoordinatorViewProvider>
          </WorkflowProvider>
        </OptimizationProvider>
      </AnalysisProvider>
    </OperationalStateProvider>
  );
}
