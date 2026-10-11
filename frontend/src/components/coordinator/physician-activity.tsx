"use client";

import { ChevronDown, CircleAlert, Info, Users } from "lucide-react";

import { SectionCard } from "@/components/shared/section-card";
import { AvailabilityBadge, TagBadge } from "@/components/shared/status-badges";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { StateFallback } from "@/components/state/state-fallback";
import type { PhysicianState } from "@/lib/api/types";
import { formatDuration, formatTime } from "@/lib/format";
import { ACTIVITY_LABELS } from "@/lib/labels";

function SignalLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}

function since(iso: string | null): string {
  return iso ? ` since ${formatTime(iso)}` : "";
}

function PhysicianRow({ p }: { p: PhysicianState }) {
  const s = p.signals;
  const warnings = p.flags.filter((f) => f.severity !== "info");
  const notes = p.flags.filter((f) => f.severity === "info");
  const sessions = [...s.active_calls, ...s.active_videos];

  return (
    <li className="py-3">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-start justify-between gap-3 rounded-md outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{p.display_name}</p>
            <p className="text-sm">{ACTIVITY_LABELS[p.activity]}</p>
            <p className="text-xs text-muted-foreground">
              {p.open_consult_ids.length} open · {p.consults_this_shift} consults ·{" "}
              {p.calls_this_shift} calls
              {p.minutes_to_shift_end !== null
                ? ` · shift ends in ${formatDuration(p.minutes_to_shift_end)}`
                : ""}
            </p>
            {p.temporary_shift ? (
              <div className="mt-1 flex flex-wrap gap-1">
                <TagBadge
                  tone={p.temporary_shift.phase === "active" ? "success" : "info"}
                  title={`Approved split shift ${p.temporary_shift.intervention_id}; routable only at ${p.temporary_shift.routing_scope_hospital_ids.join(", ")}`}
                >
                  {p.temporary_shift.phase === "active"
                    ? `Split shift · online · scope ${p.temporary_shift.routing_scope_hospital_ids.join(", ")}`
                    : "Split shift accepted · preparing (not counted yet)"}
                </TagBadge>
              </div>
            ) : null}
            {warnings.length > 0 ? (
              <div className="mt-1 flex flex-wrap gap-1">
                {warnings.map((f) => (
                  <TagBadge key={f.code} tone="warning" title={f.message}>
                    <CircleAlert className="size-3" aria-hidden />
                    {f.code.replaceAll("_", " ")}
                  </TagBadge>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <AvailabilityBadge value={p.availability} />
            <ChevronDown
              className="size-4 text-muted-foreground transition-transform group-open:rotate-180"
              aria-hidden
            />
          </div>
        </summary>
        <div className="mt-3 space-y-3 rounded-lg border bg-muted/30 p-3 text-xs">
          <div>
            <p className="mb-1 font-semibold">
              Why {p.availability.replace("_", " ")}?{" "}
              <span className="font-normal text-muted-foreground">({p.decision_rule})</span>
            </p>
            <ol className="list-decimal space-y-0.5 pl-4">
              {p.explanation.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ol>
          </div>
          <dl className="space-y-0.5">
            <SignalLine
              label="Self-reported"
              value={`${s.self_reported_status.replace("_", " ")}${since(s.status_since)}`}
            />
            <SignalLine
              label="Desktop agent"
              value={
                s.agent_online === false
                  ? `offline${since(s.agent_status_since)}`
                  : s.agent_online_inferred
                    ? "online (inferred)"
                    : "online"
              }
            />
            <SignalLine
              label="Camera"
              value={
                s.camera_active === null
                  ? "no signal"
                  : `${s.camera_active ? "active" : "inactive"}${since(s.camera_since)}`
              }
            />
            <SignalLine
              label="Synapse sessions"
              value={
                sessions.length
                  ? sessions
                      .map((x) => `${x.kind.replace("_", " ")} ${x.consult_id ?? ""}`)
                      .join(", ")
                  : "none"
              }
            />
            {s.ringing.length ? (
              <SignalLine
                label="Ringing"
                value={s.ringing.map((x) => x.consult_id ?? "call").join(", ")}
              />
            ) : null}
            <SignalLine label="Open consults" value={p.open_consult_ids.join(", ") || "none"} />
          </dl>
          {notes.length ? (
            <ul className="space-y-0.5 text-muted-foreground">
              {notes.map((f) => (
                <li key={f.code} className="flex gap-1">
                  <Info className="mt-0.5 size-3 shrink-0" aria-hidden />
                  {f.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </details>
    </li>
  );
}

export function PhysicianActivityPanel({ className }: { className?: string }) {
  const { data } = useOperationalState();
  const onShift = data?.physicians.filter((p) => p.on_shift !== false) ?? [];
  const offShift = data?.physicians.filter((p) => p.on_shift === false) ?? [];

  return (
    <SectionCard
      className={className}
      title="Physician activity"
      icon={Users}
      description="Availability derived from system signals, kept separate from consult stages. Expand a physician to see which signals decided it."
    >
      {data ? (
        <>
          <ul className="divide-y">
            {onShift.map((p) => (
              <PhysicianRow key={p.physician_id} p={p} />
            ))}
          </ul>
          {onShift.length === 0 ? (
            <p className="py-4 text-sm text-muted-foreground">
              No physicians on shift at this time.
            </p>
          ) : null}
          {offShift.length ? (
            <details className="mt-2 text-sm">
              <summary className="cursor-pointer text-muted-foreground">
                Off shift ({offShift.length})
              </summary>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {offShift.map((p) => (
                  <li key={p.physician_id}>
                    {p.display_name}
                    {p.roster_role ? ` · ${p.roster_role}` : ""}
                    {p.next_shift_starts_at
                      ? ` · next shift ${formatTime(p.next_shift_starts_at)}`
                      : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      ) : (
        <StateFallback
          feature="physician state"
          whenNoDataset="On-shift physicians and their derived activity appear once a dataset is loaded."
        />
      )}
    </SectionCard>
  );
}
