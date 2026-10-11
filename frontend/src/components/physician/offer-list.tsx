"use client";

import { Inbox } from "lucide-react";

import { EmptyState } from "@/components/shared/empty-state";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { offersApi } from "@/lib/api/endpoints";
import type { PhysicianOfferView } from "@/lib/api/types";

import { OfferCard } from "./offer-card";

function Section({
  title,
  offers,
  physicianId,
  simulationTime,
  empty,
}: {
  title: string;
  offers: PhysicianOfferView[];
  physicianId: string;
  simulationTime: string | null;
  empty?: string;
}) {
  if (!offers.length && !empty) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-navy">{title}</h2>
      {offers.length ? (
        offers.map((offer) => (
          <OfferCard
            key={offer.id}
            offer={offer}
            physicianId={physicianId}
            simulationTime={simulationTime}
          />
        ))
      ) : (
        <EmptyState compact icon={Inbox} title={empty!} />
      )}
    </section>
  );
}

/**
 * Offers for the simulated, signed-in physician. Only offers a clinical lead approved and
 * someone sent exist at all; the backend returns only this physician's own offers.
 */
export function OfferList({
  physicianId,
  versions,
  simulationTime,
}: {
  physicianId: string;
  versions: string;
  simulationTime: string | null;
}) {
  const offers = useKeyedResource(`${physicianId}|${versions}`, (signal) =>
    offersApi.mine(physicianId, signal).then((items) => ({ physicianId, items })),
  );
  // The previous doctor's offers stay in the resource while the new doctor's load; never
  // show them (with live Accept/Decline) under another name.
  const mine = offers.data?.physicianId === physicianId ? offers.data.items : null;

  if (offers.error) return <p className="text-sm text-critical">{offers.error}</p>;
  if (!mine) return <p className="text-sm text-muted-foreground">Loading offers…</p>;

  const open = mine.filter((o) => o.status === "sent");
  const committed = mine.filter((o) => o.status === "accepted" || o.status === "active");
  const past = mine.filter((o) => !open.includes(o) && !committed.includes(o));

  return (
    <div className="space-y-6">
      <Section
        title="Needs your reply"
        offers={open}
        physicianId={physicianId}
        simulationTime={simulationTime}
        empty="No offers waiting for a reply. Offers appear only after a clinical lead approves them."
      />
      <Section
        title="Your accepted shifts"
        offers={committed}
        physicianId={physicianId}
        simulationTime={simulationTime}
      />
      <Section
        title="Past offers"
        offers={past}
        physicianId={physicianId}
        simulationTime={simulationTime}
      />
    </div>
  );
}
