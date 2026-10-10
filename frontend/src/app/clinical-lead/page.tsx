import type { Metadata } from "next";

import {
  ApprovalHistory,
  InterventionDetail,
  PendingApprovals,
} from "@/components/clinical-lead/sections";
import { PageHeader } from "@/components/shared/page-header";
import { SimulationStatus } from "@/components/status/simulation-status";
import { WorkflowProvider } from "@/components/workflow/workflow-provider";

export const metadata: Metadata = { title: "Clinical Lead" };

export default function ClinicalLeadPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Clinical Lead"
        title="Intervention approvals"
        description="Review proposed interventions and their rationale. No message reaches an off-shift physician without your approval."
      />
      <SimulationStatus />
      <WorkflowProvider role="clinical_lead">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <PendingApprovals className="lg:col-span-2" />
          <InterventionDetail className="lg:col-span-3" />
          <ApprovalHistory className="lg:col-span-5" />
        </div>
      </WorkflowProvider>
    </div>
  );
}
