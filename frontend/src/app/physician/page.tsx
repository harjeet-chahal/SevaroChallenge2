import { ShieldCheck } from "lucide-react";
import type { Metadata } from "next";

import { OfferList } from "@/components/physician/offer-list";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Shift Offers" };

export default function PhysicianPage() {
  return (
    <div className="mx-auto max-w-md space-y-6">
      <PageHeader
        eyebrow="Off-Shift Physician"
        title="Shift offers"
        description="Approved requests to cover a short shift. Accept or decline from your phone."
      />
      <p className="flex items-start gap-2 rounded-lg border border-info-border bg-info-soft p-3 text-sm text-info">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        Offers never include patient information — only hospitals, hours, time to come online,
        the reason you were asked and the reply deadline.
      </p>
      <OfferList />
    </div>
  );
}
