import { ShieldCheck } from "lucide-react";
import type { Metadata } from "next";

import { OfferList } from "@/components/physician/offer-list";

export const metadata: Metadata = { title: "Shift Offers" };

export default function PhysicianPage() {
  return (
    <div className="mx-auto flex max-w-[390px] flex-col gap-3.5 pt-2 pb-10">
      <div className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold tracking-[0.14em] text-primary uppercase">Shift offers</span>
        <h1 className="text-2xl font-semibold">Approved requests to cover a short shift</h1>
      </div>
      <p className="flex items-start gap-2.5 rounded-[10px] border border-info-border bg-info-soft px-3.5 py-3 text-[13px] leading-snug text-info-ink">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
        Offers never include patient information — only hospitals, hours, time to come online, the reason you were
        asked and the reply deadline.
      </p>
      <OfferList />
    </div>
  );
}
