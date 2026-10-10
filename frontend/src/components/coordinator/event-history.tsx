"use client";

import { History } from "lucide-react";
import { useState } from "react";

import { DataEmptyState } from "@/components/shared/data-empty-state";
import { SectionCard } from "@/components/shared/section-card";
import { TagBadge } from "@/components/shared/status-badges";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { eventsApi, type EventQuery } from "@/lib/api/endpoints";
import type { EventView } from "@/lib/api/types";
import { formatTime } from "@/lib/format";
import { eventTypeLabel } from "@/lib/labels";

const PAGE = 50;

function EventFlags({ e }: { e: EventView }) {
  return (
    <div className="flex flex-wrap gap-1">
      {!e.visible ? (
        <TagBadge tone="neutral" title="Ingested after the simulation time">
          not yet ingested
        </TagBadge>
      ) : null}
      {e.dedupe_status === "duplicate" ? <TagBadge tone="neutral">duplicate</TagBadge> : null}
      {e.dedupe_status === "conflicting_duplicate" ? (
        <TagBadge tone="warning">conflicting duplicate</TagBadge>
      ) : null}
      {e.arrived_out_of_order ? (
        <TagBadge
          tone="info"
          title={`Arrived ${Math.round(e.ingest_lag_seconds)} s after it happened`}
        >
          late
        </TagBadge>
      ) : null}
      {!e.recognized ? <TagBadge tone="warning">unknown type</TagBadge> : null}
      {e.source === "live_ingest" ? <TagBadge tone="success">injected</TagBadge> : null}
      {e.source === "workflow" ? (
        <TagBadge tone="info" title="Recorded by an applied intervention (simulated Synapse action)">
          workflow
        </TagBadge>
      ) : null}
      {e.applied ? <TagBadge tone="neutral">applied</TagBadge> : null}
    </div>
  );
}

/** Debug view of the raw event log, annotated by the backend for the current simulation time. */
export function EventHistory({ className }: { className?: string }) {
  const { config } = useSystemStatus();
  const { data: state } = useOperationalState();
  const [filters, setFilters] = useState<EventQuery>({ visibility: "all", dedupe: "all" });
  const [draft, setDraft] = useState({ physician: "", consult: "" });
  const [limit, setLimit] = useState(PAGE);

  const key = config?.dataset_loaded
    ? `${config.data_version}|${config.simulation_time}|${JSON.stringify(filters)}|${limit}`
    : null;
  const events = useKeyedResource(key, (signal) =>
    eventsApi.list({ ...filters, limit, order: "ingested_desc" }, signal),
  );
  const page = events.data;

  return (
    <SectionCard
      className={className}
      title="Event history"
      icon={History}
      description="The stored event log, newest arrival first. Badges show how each event was treated at the current simulation time."
    >
      {config?.dataset_loaded ? (
        <div className="space-y-3">
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setLimit(PAGE);
              setFilters((f) => ({
                ...f,
                physician_id: draft.physician.trim() || undefined,
                consult_id: draft.consult.trim() || undefined,
              }));
            }}
          >
            <label className="text-xs">
              <span className="mb-1 block text-muted-foreground">Physician</span>
              <select
                className="h-8 rounded-lg border bg-background px-2 text-sm"
                value={draft.physician}
                onChange={(e) => setDraft((d) => ({ ...d, physician: e.target.value }))}
              >
                <option value="">Any</option>
                {state?.physicians.map((p) => (
                  <option key={p.physician_id} value={p.physician_id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs">
              <span className="mb-1 block text-muted-foreground">Consult ID</span>
              <Input
                className="h-8 w-36"
                value={draft.consult}
                onChange={(e) => setDraft((d) => ({ ...d, consult: e.target.value }))}
              />
            </label>
            <label className="text-xs">
              <span className="mb-1 block text-muted-foreground">Visibility</span>
              <select
                className="h-8 rounded-lg border bg-background px-2 text-sm"
                value={filters.visibility}
                onChange={(e) =>
                  setFilters((f) => ({
                    ...f,
                    visibility: e.target.value as EventQuery["visibility"],
                  }))
                }
              >
                <option value="all">All</option>
                <option value="visible">Known now</option>
                <option value="pending">Not yet ingested</option>
              </select>
            </label>
            <label className="text-xs">
              <span className="mb-1 block text-muted-foreground">Duplicates</span>
              <select
                className="h-8 rounded-lg border bg-background px-2 text-sm"
                value={filters.dedupe}
                onChange={(e) =>
                  setFilters((f) => ({ ...f, dedupe: e.target.value as EventQuery["dedupe"] }))
                }
              >
                <option value="all">All</option>
                <option value="canonical">Canonical only</option>
                <option value="duplicates">Duplicates only</option>
              </select>
            </label>
            <Button type="submit" size="sm" variant="outline">
              Apply
            </Button>
            {page ? (
              <span className="ml-auto text-xs text-muted-foreground">
                {page.items.length} of {page.total} events
              </span>
            ) : null}
          </form>

          {events.error ? <p className="text-sm text-critical">{events.error}</p> : null}
          {page ? (
            <div className="-mx-4 max-h-[28rem] overflow-auto">
              <Table className="min-w-[760px]">
                <TableHeader className="sticky top-0 bg-card">
                  <TableRow>
                    <TableHead className="pl-4">Ingested (UTC)</TableHead>
                    <TableHead>Event time (as sent)</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Consult</TableHead>
                    <TableHead>Physician</TableHead>
                    <TableHead className="pr-4">Treatment</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {page.items.map((e) => (
                    <TableRow key={e.sequence} className={e.visible ? undefined : "opacity-60"}>
                      <TableCell className="pl-4 tabular-nums">
                        {formatTime(e.ingested_at, "UTC", true)}
                      </TableCell>
                      <TableCell className="font-mono text-xs" title={e.description ?? undefined}>
                        {e.event_time_raw}
                      </TableCell>
                      <TableCell>
                        <span className="block">{eventTypeLabel(e.event_type)}</span>
                        <span className="text-xs text-muted-foreground">{e.event_id}</span>
                      </TableCell>
                      <TableCell>{e.consult_id ?? "—"}</TableCell>
                      <TableCell>{e.physician_id ?? "—"}</TableCell>
                      <TableCell className="pr-4">
                        <EventFlags e={e} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
          {page && page.total > page.items.length ? (
            <Button variant="outline" size="sm" onClick={() => setLimit((l) => l + PAGE)}>
              Load more
            </Button>
          ) : null}
        </div>
      ) : (
        <DataEmptyState
          feature="event log"
          whenNoDataset="The event log appears once a dataset is loaded."
        />
      )}
    </SectionCard>
  );
}
