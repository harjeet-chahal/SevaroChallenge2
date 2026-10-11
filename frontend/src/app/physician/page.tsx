import { ShieldCheck } from "lucide-react";
import type { Metadata } from "next";

import { PhysicianPortal } from "@/components/physician/physician-portal";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Shift Offers & Availability" };

export default function PhysicianPage() {
  return (
    <div className="mx-auto flex max-w-md flex-col gap-[22px]">
      <PageHeader
        eyebrow="Off-shift physician"
        title="Shift offers"
        description="Share when you could cover an extra shift, and accept or decline approved requests from your phone."
      />
      <div className="rounded-xl border border-info-border bg-info-soft px-4 py-3">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-info-ink">
          <ShieldCheck className="size-4 shrink-0" aria-hidden />
          No patient information
        </p>
        <p className="mt-0.5 text-caption text-foreground-2">
          Offers show only hospitals, hours, time to come online, the reason you were asked and
          the reply deadline.
        </p>
      </div>
      <PhysicianPortal />
    </div>
  );
}
