"use client";

import { ArrowDownRight, ArrowUpRight, Repeat2, Scale } from "lucide-react";

import { SectionCard } from "@/components/shared/section-card";
import { SeverityBadge } from "@/components/shared/severity-badge";
import { useLiveResource } from "@/hooks/use-live-resource";
import { formatTime } from "@/lib/format";
import { neurogridApi } from "@/lib/api/neurogrid";

import { Gate, KeyValue, Pill, fmtMin, fmtPm } from "./kit";

const ET = "America/New_York";

export function HandoffPanel({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.handoff(s));
  return (
    <SectionCard
      className={className}
      title="Shift handoff intelligence"
      icon={Repeat2}
      description="Who leaves and who arrives in the forecast window, what work they hold, how coverage changes, and which deadlines come due."
    >
      <Gate resource={res} feature="shift handoff">
        {(r) => (
          <div className="space-y-4">
            {r.transitions.length === 0 ? (
              <p className="text-sm text-muted-foreground">No shift changes in the next {r.horizon_minutes} min.</p>
            ) : (
              <ol className="space-y-2">
                {r.transitions.map((t) => (
                  <li key={`${t.physician_id}-${t.at}-${t.kind}`} className="rounded-lg border bg-card/60 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      {t.kind === "departing" ? (
                        <Pill tone="warning" icon={ArrowUpRight}>departing</Pill>
                      ) : (
                        <Pill tone="success" icon={ArrowDownRight}>arriving</Pill>
                      )}
                      <span className="font-semibold">{t.display_name}</span>
                      <span className="text-sm text-muted-foreground tabular-nums">{formatTime(t.at, ET)}</span>
                      <Pill tone={t.certainty === "scheduled" ? "muted" : "info"}>{t.certainty.replace("_", " ")}</Pill>
                      {t.risk !== "ok" ? <Pill tone={t.risk === "critical" ? "critical" : "warning"}>{t.risk}</Pill> : null}
                    </div>
                    {t.open_consults.length ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Holding:{" "}
                        {t.open_consults
                          .map((c) => `${c.consult_id} (${c.stage.replaceAll("_", " ")}${c.unfinished_note ? ", note open" : ""})`)
                          .join(", ")}
                      </p>
                    ) : null}
                    {t.coverage_changes.filter((c) => c.counted_before !== c.counted_after).length ? (
                      <p className="mt-1 text-xs">
                        {t.coverage_changes
                          .filter((c) => c.counted_before !== c.counted_after)
                          .map((c) => `${c.hospital_name} ${c.counted_before}→${c.counted_after}/${c.required_after ?? "—"}${(c.deficit_after ?? 0) > 0 ? " SHORT" : ""}`)
                          .join(" · ")}
                      </p>
                    ) : null}
                    {t.notes.length ? <p className="mt-1 text-xs text-muted-foreground">{t.notes.join(" ")}</p> : null}
                  </li>
                ))}
              </ol>
            )}
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <h3 className="mb-1 text-sm font-semibold">Upcoming critical deadlines</h3>
                <ul className="space-y-1 text-sm">
                  {r.deadlines.map((d) => (
                    <li key={`${d.consult_id}-${d.rule_code}`} className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={d.severity_now} />
                      <span className="font-medium">{d.consult_id}</span>
                      <span className="text-xs text-muted-foreground">{d.stage}</span>
                      <span className="ml-auto text-xs tabular-nums">
                        {d.minutes_to_critical !== null && d.minutes_to_critical <= 0
                          ? `critical for ${fmtMin(-d.minutes_to_critical)}`
                          : `critical in ${fmtMin(d.minutes_to_critical)}`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="space-y-2">
                <h3 className="text-sm font-semibold">Pending routing failures &amp; rescues</h3>
                {r.pending_routing_failures.map((p) => (
                  <p key={String(p.consult_id)} className="text-xs">
                    {String(p.consult_id)} at {String(p.hospital_name)} — failed {String(p.routing_failures)}× (next retry{" "}
                    {p.next_retry_at ? formatTime(String(p.next_retry_at), ET) : "—"})
                  </p>
                ))}
                {r.pending_rescues.map((p) => (
                  <p key={String(p.intervention_id)} className="text-xs">
                    {String(p.intervention_id)} · {String(p.type)} · {String(p.status)} — {String(p.title)}
                  </p>
                ))}
                {!r.pending_routing_failures.length && !r.pending_rescues.length ? (
                  <p className="text-xs text-muted-foreground">None.</p>
                ) : null}
              </div>
            </div>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}

export function CoverageDebtPanel({ className }: { className?: string }) {
  const res = useLiveResource((s) => neurogridApi.coverageDebt(s));
  return (
    <SectionCard
      className={className}
      title="Coverage debt"
      icon={Scale}
      description="Accumulated uncovered physician-minutes. History is reconstructed by replaying earlier states; the projection is the forecast. They are never mixed."
    >
      <Gate resource={res} feature="coverage debt">
        {(r) => (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <KeyValue label={`Historical (last ${r.lookback_minutes} min)`} value={fmtPm(r.network_historical)} hint="reconstructed" />
              <KeyValue label={`Projected (next ${r.horizon_minutes} min)`} value={fmtPm(r.network_projected)} hint="forecast" />
              <KeyValue label="Projected, confirmed only" value={fmtPm(r.network_projected_if_uncertain_excluded)} hint="uncertain capacity excluded" />
              <KeyValue label="Fragile coverage" value={fmtMin(r.network_fragile_minutes)} hint="hospital-minutes at zero spare" />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="py-1 text-left font-medium">Hospital</th>
                    <th className="text-right font-medium">Historical</th>
                    <th className="text-right font-medium">Projected</th>
                    <th className="text-right font-medium">Confirmed-only</th>
                    <th className="text-right font-medium">Fragile</th>
                  </tr>
                </thead>
                <tbody>
                  {r.hospitals.map((h) => (
                    <tr key={h.hospital_id} className="border-t">
                      <td className="py-1">{h.hospital_name}</td>
                      <td className="text-right tabular-nums">{h.historical_debt_physician_minutes}</td>
                      <td className="text-right tabular-nums">{h.projected_debt_physician_minutes}</td>
                      <td className="text-right tabular-nums">{h.projected_debt_if_uncertain_excluded}</td>
                      <td className="text-right tabular-nums">{fmtMin(h.fragile_minutes_projected)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}
