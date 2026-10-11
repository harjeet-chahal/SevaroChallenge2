import { ShieldCheck } from "lucide-react";
import type { Metadata } from "next";

import { PhysicianPortal } from "@/components/physician/physician-portal";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Shift Offers & Availability" };

export default function PhysicianPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <PageHeader
        eyebrow="Off-Shift Physician"
        title="Shift offers"
        description="Share when you could cover an extra shift, and accept or decline approved requests from your phone."
      />
      <p className="flex items-start gap-2 rounded-lg border border-info-border bg-info-soft p-3 text-sm text-info">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        Offers never include patient information — only hospitals, hours, time to come online,
        the reason you were asked and the reply deadline.
      </p>
      <PhysicianPortal />
    </div>
  );
}
