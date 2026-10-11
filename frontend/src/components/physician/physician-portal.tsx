"use client";

import { Inbox, UserRound } from "lucide-react";
import { useState } from "react";

import { DataEmptyState } from "@/components/shared/data-empty-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { offersApi } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/format";

import { AvailabilityPanel } from "./availability-panel";
import { OfferList } from "./offer-list";

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

/**
 * The off-shift physician's phone view for one simulated, signed-in physician: share
 * voluntary availability, and answer offers. The backend returns only this physician's own
 * availability and offers.
 */
export function PhysicianPortal() {
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
  const known = people.find((p) => p.physician_id === picked)?.physician_id ?? null;
  // The first default sticks: answering an offer must not silently switch the simulated user.
  // A remembered id that is not in this list (e.g. picked under another dataset) is replaced
  // the same way, once, and the replacement is remembered.
  if (known === null && fallback !== null) {
    if (picked !== null) store(fallback);
    setPicked(fallback);
  }
  const physicianId = known ?? fallback;

  if (availability === "checking" || availability === "offline" || availability === "degraded" || !loaded) {
    return <DataEmptyState feature="offers" whenNoDataset="No dataset is loaded, so there are no offers." />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-1 rounded-lg border bg-card p-3">
        <label htmlFor="simulated-physician" className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
          <UserRound className="size-3.5" aria-hidden />
          Signed in as (simulated)
        </label>
        <select
          id="simulated-physician"
          className="h-10 w-full rounded-md border bg-background px-2 text-base"
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

      {recipients.error ? (
        <p className="text-sm text-critical-ink">{recipients.error}</p>
      ) : !recipients.data ? (
        <p className="text-sm text-muted-foreground">Loading offers…</p>
      ) : !physicianId ? (
        <EmptyState compact icon={Inbox} title="No off-shift physicians in this dataset" />
      ) : (
        <>
          <AvailabilityPanel physicianId={physicianId} versions={versions} />
          <OfferList
            physicianId={physicianId}
            versions={versions}
            simulationTime={config?.simulation_time ?? null}
          />
        </>
      )}
    </div>
  );
}
