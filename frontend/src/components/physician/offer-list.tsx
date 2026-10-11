"use client";

import { Inbox, UserRound } from "lucide-react";
import { useState } from "react";

import { DataEmptyState } from "@/components/shared/data-empty-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { offersApi } from "@/lib/api/endpoints";
import type { PhysicianOfferView } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

import { ExtraAvailability } from "./extra-availability";

import { OfferCard } from "./offer-card";

const STORAGE_KEY = "sevaro-pulse:simulated-physician";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function store(value: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Storage blocked (private mode): the choice simply is not remembered.
  }
}

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
      <h2 className="text-lg font-semibold text-foreground">{title}</h2>
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
export function OfferList() {
  const { availability, config } = useSystemStatus();
  // Server render shows the loading/empty state, so reading storage lazily is safe here.
  const [picked, setPicked] = useState<string | null>(() =>
    typeof window === "undefined" ? null : readStored(),
  );

  const loaded = Boolean(config?.dataset_loaded);
  const versions = config ? `${config.workflow_version}|${config.data_version}|${config.simulation_time}` : "";
  const recipients = useKeyedResource(loaded ? `recipients|${versions}` : null, (signal) =>
    offersApi.recipients(signal),
  );
  const people = recipients.data ?? [];
  const fallback =
    people.find((p) => p.open_offers > 0)?.physician_id ?? people[0]?.physician_id ?? null;
  // The first default sticks: answering an offer must not silently switch the simulated user.
  if (picked === null && fallback !== null) setPicked(fallback);
  const physicianId = people.find((p) => p.physician_id === picked)?.physician_id ?? fallback;
  const offers = useKeyedResource(physicianId ? `${physicianId}|${versions}` : null, (signal) =>
    offersApi.mine(physicianId!, signal),
  );

  if (availability === "checking" || availability === "offline" || availability === "degraded" || !loaded) {
    return <DataEmptyState feature="offers" whenNoDataset="No dataset is loaded, so there are no offers." />;
  }

  const all = offers.data ?? [];
  const open = all.filter((o) => o.status === "sent");
  const committed = all.filter((o) => o.status === "accepted" || o.status === "active");
  const past = all.filter((o) => !open.includes(o) && !committed.includes(o));

  return (
    <div className="space-y-6">
      <div className="space-y-1.5">
        <label htmlFor="simulated-physician" className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <UserRound className="size-3.5" aria-hidden />
          Signed in as (simulated)
        </label>
        <select
          id="simulated-physician"
          className="min-h-11 w-full rounded-[10px] border border-border-strong bg-card px-3 text-[15px]"
          value={physicianId ?? ""}
          onChange={(e) => {
            setPicked(e.target.value);
            store(e.target.value);
          }}
        >
          {people.map((p) => (
            <option key={p.physician_id} value={p.physician_id}>
              {p.display_name}
              {p.open_offers ? ` — ${p.open_offers} new offer${p.open_offers > 1 ? "s" : ""}` : ""}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">
          Demo stand-in for a login (not real authentication). Simulated time now:{" "}
          {config?.simulation_time ? formatDateTime(config.simulation_time) : "—"}
        </p>
      </div>

      {physicianId && <ExtraAvailability key={physicianId} physicianId={physicianId} />}

      {offers.error ? <p className="text-sm text-critical-ink">{offers.error}</p> : null}
      {!offers.data && !offers.error ? (
        <p className="text-sm text-muted-foreground">Loading offers…</p>
      ) : physicianId ? (
        <>
          <Section
            title="Needs your reply"
            offers={open}
            physicianId={physicianId}
            simulationTime={config?.simulation_time ?? null}
            empty="No offers waiting for a reply. Offers appear only after a clinical lead approves them."
          />
          <Section
            title="Your accepted shifts"
            offers={committed}
            physicianId={physicianId}
            simulationTime={config?.simulation_time ?? null}
          />
          <Section
            title="Past offers"
            offers={past}
            physicianId={physicianId}
            simulationTime={config?.simulation_time ?? null}
          />
        </>
      ) : (
        <EmptyState compact icon={Inbox} title="No off-shift physicians in this dataset" />
      )}
    </div>
  );
}
