"use client";

import { ChevronRight, Inbox } from "lucide-react";
import { Fragment, useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { StageBadge, TagBadge } from "@/components/shared/status-badges";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { StateFallback } from "@/components/state/state-fallback";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ConsultationState } from "@/lib/api/types";
import { formatElapsed, formatTime } from "@/lib/format";
import { STAGE_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

import { type ConsultFilter, useCoordinatorView } from "./view-provider";

function ConsultDetail({ c, names }: { c: ConsultationState; names: Map<string, string> }) {
  const tz = c.hospital_timezone;
  return (
    <div className="grid gap-3 p-3 text-xs sm:grid-cols-2">
      <div>
        <p className="mb-1 font-semibold">Stage history ({tz ?? "viewer time"})</p>
        <ol className="space-y-0.5">
          {c.stage_history.map((h) => (
            <li key={`${h.event_id}-${h.stage}`} className="flex gap-2">
              <span className="w-20 shrink-0 tabular-nums text-muted-foreground">
                {formatTime(h.entered_at, tz)}
              </span>
              <span>
                {STAGE_LABELS[h.stage]}
                {h.provisional ? " (provisional)" : ""}
                <span className="text-muted-foreground"> · {h.event_type}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
      <div className="space-y-2">
        <p>
          Received {c.received_at ? formatTime(c.received_at, tz) : "— (no consult_received event)"}
          {c.seconds_since_received !== null
            ? ` · ${formatElapsed(c.seconds_since_received)} ago`
            : ""}
        </p>
        {c.assignment_history.length ? (
          <div>
            <p className="mb-1 font-semibold">Assignments</p>
            <ul className="space-y-0.5">
              {c.assignment_history.map((a) => (
                <li key={a.event_id}>
                  {formatTime(a.at, tz)} · {names.get(a.physician_id) ?? a.physician_id}
                  {a.inferred ? " (inferred)" : ""}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {c.routing_failures > 0 ? (
          <p>
            Routing failed {c.routing_failures}× (last {formatTime(c.last_routing_failure_at!, tz)}
            ).
          </p>
        ) : null}
        {c.anomalies.length ? (
          <div>
            <p className="mb-1 font-semibold">Anomalies</p>
            <ul className="space-y-0.5 text-warning">
              {c.anomalies.map((a, i) => (
                <li key={i}>{a.message}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

const FILTER_LABELS: Record<ConsultFilter, string> = {
  open: "Open",
  unassigned: "Unassigned",
  all: "All incl. signed off",
};

export function ConsultationQueue({ className }: { className?: string }) {
  const { data } = useOperationalState();
  const { consultFilter: filter, setConsultFilter: setFilter } = useCoordinatorView();
  const [expanded, setExpanded] = useState<string | null>(null);

  const names = new Map(data?.physicians.map((p) => [p.physician_id, p.display_name]) ?? []);
  const all = data?.consultations ?? [];
  const matches: Record<ConsultFilter, (c: ConsultationState) => boolean> = {
    open: (c) => c.is_open,
    unassigned: (c) => c.is_open && !c.assigned_physician_id,
    all: () => true,
  };
  const consults = all.filter(matches[filter]);

  return (
    <SectionCard
      className={className}
      title="Consultations"
      icon={Inbox}
      info="Each consult's lifecycle, rebuilt from events and independent of physician activity. Times are in the hospital's local zone. Expand a consult for its stage and assignment history."
      action={
        data ? (
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label="Filter consults"
          >
            {(Object.keys(FILTER_LABELS) as ConsultFilter[]).map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs font-medium outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                  filter === f
                    ? "border-primary bg-primary text-primary-foreground"
                    : "bg-card text-muted-foreground hover:bg-muted",
                )}
              >
                {FILTER_LABELS[f]}{" "}
                <span className="tabular-nums">{all.filter(matches[f]).length}</span>
              </button>
            ))}
          </div>
        ) : null
      }
    >
      {data ? (
        consults.length ? (
          <div className="-mx-4 overflow-x-auto">
            <Table className="min-w-[540px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Consult</TableHead>
                  <TableHead>Hospital</TableHead>
                  <TableHead>Stage · time in stage</TableHead>
                  <TableHead className="pr-4">Physician</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {consults.map((c) => {
                  const open = expanded === c.consult_id;
                  return (
                    <Fragment key={c.consult_id}>
                      <TableRow className={cn(open && "bg-muted/40")}>
                        <TableCell className="pl-4">
                          <button
                            type="button"
                            className="flex items-center gap-1 rounded font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring/50"
                            aria-expanded={open}
                            onClick={() => setExpanded(open ? null : c.consult_id)}
                          >
                            <ChevronRight
                              className={cn("size-3.5 transition-transform", open && "rotate-90")}
                              aria-hidden
                            />
                            {c.consult_id}
                          </button>
                          <span className="block pl-4.5 text-xs text-muted-foreground">
                            {c.consult_type ?? "type unknown"}
                            {c.priority ? ` · ${c.priority}` : ""}
                          </span>
                        </TableCell>
                        <TableCell
                          className="max-w-40 truncate"
                          title={c.hospital_name ?? undefined}
                        >
                          {c.hospital_name ?? c.hospital_id ?? "—"}
                        </TableCell>
                        <TableCell>
                          <StageBadge stage={c.stage} />
                          <span className="block text-xs text-muted-foreground tabular-nums">
                            {formatElapsed(c.seconds_in_stage)}
                          </span>
                        </TableCell>
                        <TableCell className="pr-4">
                          {c.assigned_physician_id ? (
                            (names.get(c.assigned_physician_id) ?? c.assigned_physician_id)
                          ) : (
                            <TagBadge tone="warning">Unassigned</TagBadge>
                          )}
                          {c.routing_failures > 0 ? (
                            <span className="block text-xs text-muted-foreground">
                              {c.routing_failures} routing failure(s)
                            </span>
                          ) : null}
                        </TableCell>
                      </TableRow>
                      {open ? (
                        <TableRow className="bg-muted/20 hover:bg-muted/20">
                          <TableCell colSpan={4} className="p-0 whitespace-normal">
                            <ConsultDetail c={c} names={names} />
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className="py-4 text-sm text-muted-foreground">
            {filter === "unassigned"
              ? "Every open consult has a physician."
              : "No open consults at this time."}
          </p>
        )
      ) : (
        <StateFallback
          feature="consultation state"
          whenNoDataset="Open consults, their stage and assignment appear once a dataset is loaded."
        />
      )}
    </SectionCard>
  );
}
