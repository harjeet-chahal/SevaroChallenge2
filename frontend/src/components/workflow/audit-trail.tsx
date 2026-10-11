"use client";

import { History } from "lucide-react";

import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { workflowApi } from "@/lib/api/endpoints";
import type { AuditEntry, DemoUserRole } from "@/lib/api/types";
import { formatTime } from "@/lib/format";
import { AUDIT_ACTION_LABELS } from "@/lib/labels";
import { cn } from "@/lib/utils";

const ROLE_LABELS: Record<string, string> = {
  coordinator: "Coordinator",
  clinical_lead: "Clinical lead",
  physician: "Physician",
  system: "System (simulation policy)",
};

function Row({ entry, tz }: { entry: AuditEntry; tz?: string | null }) {
  return (
    <li className="grid grid-cols-[6rem_1fr] gap-2 py-1.5 text-xs">
      <time
        dateTime={entry.occurred_at}
        className="text-muted-foreground font-mono tabular-nums"
        title={`Simulation time ${entry.occurred_at}; recorded ${entry.recorded_at} (wall clock)`}
      >
        {formatTime(entry.occurred_at, tz)}
      </time>
      <div className="min-w-0 space-y-0.5">
        <p>
          <span className="font-semibold">{AUDIT_ACTION_LABELS[entry.action] ?? entry.action}</span>
          {entry.from_status || entry.to_status ? (
            <span className="text-muted-foreground">
              {" "}
              · {entry.from_status ?? "—"} → {entry.to_status ?? "—"}
            </span>
          ) : null}
          <span className="text-muted-foreground">
            {" "}
            · {ROLE_LABELS[entry.actor.role] ?? entry.actor.role}
            {entry.actor.actor_id ? ` (${entry.actor.actor_id})` : ""}
          </span>
        </p>
        <p className="break-words text-muted-foreground">{entry.summary}</p>
      </div>
    </li>
  );
}

/**
 * Compact, append-only history. Times are simulation times (hover for the wall-clock
 * recording time). ``interventionId`` narrows it to one intervention and its offers.
 */
export function AuditTrail({
  role,
  versionKey,
  interventionId,
  limit = 100,
  tz,
  className,
  emptyText = "No workflow activity yet.",
}: {
  role: DemoUserRole;
  versionKey: string | null;
  interventionId?: string;
  limit?: number;
  tz?: string | null;
  className?: string;
  emptyText?: string;
}) {
  const key = versionKey ? `${versionKey}|${interventionId ?? "all"}|${limit}` : null;
  const audit = useKeyedResource(key, (signal) =>
    workflowApi.audit(role, { intervention_id: interventionId, limit }, signal),
  );
  const items = audit.data?.items ?? [];
  // Chronological for one intervention (a story), newest first for the global feed.
  const ordered = interventionId ? [...items].reverse() : items;
  return (
    <div className={cn("space-y-1", className)}>
      <h4 className="flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
        <History className="size-3.5" aria-hidden />
        Audit trail{audit.data ? ` (${audit.data.total})` : ""}
      </h4>
      {audit.error ? <p className="text-xs text-critical-ink">{audit.error}</p> : null}
      {!audit.data && !audit.error ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-xs text-muted-foreground">{emptyText}</p>
      ) : (
        <ol className="max-h-80 divide-y overflow-y-auto rounded-md border px-2">
          {ordered.map((entry) => (
            <Row key={entry.id} entry={entry} tz={tz} />
          ))}
        </ol>
      )}
    </div>
  );
}
