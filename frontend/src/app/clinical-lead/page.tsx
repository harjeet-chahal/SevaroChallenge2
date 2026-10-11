import type { Metadata } from "next";

import {
  ApprovalHistory,
  InterventionDetail,
  PendingApprovals,
} from "@/components/clinical-lead/sections";
import { FreshnessLockBanner } from "@/components/neurogrid/contracts";
import { PageHeader } from "@/components/shared/page-header";
import { WorkflowProvider } from "@/components/workflow/workflow-provider";

export const metadata: Metadata = { title: "Clinical Lead" };

export default function ClinicalLeadPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Clinical Lead approvals"
        description="Review each proposed rescue and its rationale. Nothing reaches a physician without your approval, and approving re-validates the plan against fresh state."
      />
      <WorkflowProvider role="clinical_lead">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <FreshnessLockBanner className="lg:col-span-5" />
          <PendingApprovals className="lg:col-span-2" />
          <InterventionDetail className="lg:col-span-3" />
          <ApprovalHistory className="lg:col-span-5" />
        </div>
      </WorkflowProvider>
    </div>
  );
}
