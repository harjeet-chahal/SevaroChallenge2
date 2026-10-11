"use client";

import { ArrowRight, BadgeCheck, Ban, FlaskRound, Sparkles, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { Button } from "@/components/ui/button";
import { useLiveResource } from "@/hooks/use-live-resource";
import { ApiError } from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";
import { formatTime } from "@/lib/format";
import { neurogridApi, type RescueOption, type RescueSimulation } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { Gate, Pill, fmtMin } from "./kit";

const ET = "America/New_York";

const KIND_LABEL: Record<RescueOption["kind"], string> = {
  do_nothing: "No action",
  escalation: "Escalation",
  reassignment: "Consult reassignment",
  split_shift: "Off-duty extra shift",
  shift_extension: "Shift extension",
  combination: "Coordinated plan",
};

function Delta({ before, after, unit = "" }: { before: number; after: number; unit?: string }) {
  const better = after < before;
  const worse = after > before;
  return (
    <span className="tabular-nums">
      {before}
      <ArrowRight className="mx-1 inline size-3 text-muted-foreground" aria-hidden />
      <b className={cn(better && "text-success", worse && "text-critical")}>{after}</b>
      {unit}
    </span>
  );
}

function OptionCard({ o, sim, onPropose, busy }: { o: RescueOption; sim: RescueSimulation; onPropose: (o: RescueOption) => void; busy: boolean }) {
  const out = o.outcome;
  return (
    <li
      className={cn(
        "flex flex-col gap-3 rounded-xl border p-4",
        o.recommended ? "border-primary bg-primary/5" : o.feasible ? "bg-card" : "bg-muted/30 opacity-90",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-bold text-muted-foreground tabular-nums">#{o.rank}</span>
        <Pill tone="muted">{KIND_LABEL[o.kind]}</Pill>
        {o.recommended ? <Pill tone="primary" icon={Sparkles}>recommended</Pill> : null}
        {o.simulation_only ? <Pill tone="warning" icon={FlaskRound}>simulation only</Pill> : null}
        {!o.feasible && !o.simulation_only ? <Pill tone="critical" icon={Ban}>infeasible</Pill> : null}
        {o.requires_approval && o.feasible ? <Pill tone="info">needs clinical-lead approval</Pill> : null}
      </div>
      <p className="font-semibold">{o.label}</p>
      {out ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Target deficit</dt>
          <dd><Delta before={out.target_deficit_before} after={out.target_deficit_after} /> <span className="text-xs text-muted-foreground">phys-min</span></dd>
          <dt className="text-muted-foreground">Network deficit</dt>
          <dd><Delta before={out.network_deficit_before} after={out.network_deficit_after} /></dd>
          <dt className="text-muted-foreground">New shortfalls</dt>
          <dd className={cn("tabular-nums", out.new_shortfall_hospital_ids.length && "text-critical")}>{out.new_shortfall_hospital_ids.length ? out.new_shortfall_hospital_ids.join(", ") : "none"}</dd>
          <dt className="text-muted-foreground">Single points</dt>
          <dd><Delta before={out.single_points_before} after={out.single_points_after} /></dd>
          <dt className="text-muted-foreground">Activation</dt>
          <dd className="tabular-nums">{out.activation_at ? `${formatTime(out.activation_at, ET)} (+${fmtMin(out.activation_delay_minutes)})` : "—"}</dd>
          <dt className="text-muted-foreground">Resolved</dt>
          <dd>{out.resolved_hospital_ids.join(", ") || "—"}</dd>
        </dl>
      ) : null}
      {o.workload ? (
        <p className="rounded-md bg-muted/50 px-2 py-1.5 text-xs">
          Load guardian: protected routing sends {String(o.workload.protected_routed_to_joiner)} modeled consults
          ({String(o.workload.protected_elsewhere)} outside the gap) vs {String(o.workload.unrestricted_routed_to_joiner)} unrestricted
          ({String(o.workload.unrestricted_elsewhere)} outside).
        </p>
      ) : null}
      {o.blocking_reasons.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-xs text-critical">
          {o.blocking_reasons.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      ) : null}
      {o.why.length ? (
        <details open={o.recommended} className="text-xs">
          <summary className="cursor-pointer font-medium">Why this option?</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
            {o.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
            {o.uncertainty.map((w) => (
              <li key={w}>Uncertainty: {w}</li>
            ))}
          </ul>
          <p className="mt-1 text-muted-foreground">Lexicographic key: [{o.lexicographic_key.map((k) => (k > 1e8 ? "∞" : k)).join(", ")}]</p>
        </details>
      ) : null}
      {o.proposal && o.feasible && !o.simulation_only && o.kind !== "do_nothing" ? (
        <Button size="sm" className="mt-auto self-start" disabled={busy} onClick={() => onPropose(o)}>
          <Workflow className="size-4" aria-hidden />
          Create rescue contract
        </Button>
      ) : null}
      <span className="sr-only">{sim.label}</span>
    </li>
  );
}

function TargetPicker() {
  const router = useRouter();
  const params = useSearchParams();
  const lsm = useLiveResource((s) => neurogridApi.lastSafeMoment(s));
  const fragility = useLiveResource((s) => neurogridApi.fragility(s));
  const hospitals = fragility.data?.hospitals ?? [];
  const current = params.get("hospital") ?? "";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <label htmlFor="sim-target" className="font-medium">
        Target
      </label>
      <select
        id="sim-target"
        value={current}
        onChange={(e) => router.replace(e.target.value ? `/simulator?hospital=${e.target.value}` : "/simulator")}
        className="rounded-md border bg-card px-2 py-1"
      >
        <option value="">Most urgent projected shortfall</option>
        {hospitals.map((h) => (
          <option key={h.hospital_id} value={h.hospital_id}>
            {h.hospital_name} ({h.status})
          </option>
        ))}
      </select>
      {lsm.data?.items.slice(0, 3).map((i) => (
        <Button key={i.hospital_id} size="sm" variant="outline" onClick={() => router.replace(`/simulator?hospital=${i.hospital_id}`)}>
          {i.hospital_name} · short {formatTime(i.shortfall_at, i.timezone)}
        </Button>
      ))}
    </div>
  );
}

export function RescueSimulator() {
  const params = useSearchParams();
  const hospital = params.get("hospital");
  const alert = params.get("alert");
  const res = useLiveResource(
    (s) => neurogridApi.simulate({ hospitalIds: hospital ? [hospital] : undefined, alertId: alert }, s),
    `${hospital}|${alert}`,
  );
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string; id?: string } | null>(null);

  async function propose(o: RescueOption) {
    setBusy(true);
    setResult(null);
    try {
      const iv = await neurogridApi.propose(o.proposal ?? {});
      setResult({ ok: true, text: `${iv.id} created — ${iv.status.replaceAll("_", " ")}. Nobody has been contacted.`, id: iv.id });
    } catch (e) {
      const details = e instanceof ApiError ? (e.details as { blocking_reasons?: string[] } | null) : null;
      setResult({ ok: false, text: [describeError(e), ...(details?.blocking_reasons ?? [])].join(" ") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="Rescue Impact Simulator"
      icon={Workflow}
      description="Every option is applied to an isolated copy of the forecast and re-evaluated network-wide. Ranked by hard constraints first, then outcome — a minor efficiency gain never outranks a worse safety result."
    >
      <div className="mb-4">
        <TargetPicker />
      </div>
      <Gate resource={res} feature="the rescue simulator">
        {(sim) => (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone="info">{sim.label}</Pill>
              <span className="text-sm font-medium">{sim.target_label}</span>
            </div>
            {result ? (
              <div
                role="status"
                className={cn(
                  "flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm",
                  result.ok ? "border-success-border bg-success-soft text-success" : "border-critical-border bg-critical-soft text-critical",
                )}
              >
                {result.ok ? <BadgeCheck className="size-4" aria-hidden /> : <Ban className="size-4" aria-hidden />}
                {result.text}
                {result.ok ? (
                  <Button asChild size="sm" variant="outline" className="ml-auto">
                    <Link href="/contracts">Follow it in Rescue Contracts</Link>
                  </Button>
                ) : null}
              </div>
            ) : null}
            <ul className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {sim.options.map((o) => (
                <OptionCard key={o.option_id} o={o} sim={sim} onPropose={propose} busy={busy} />
              ))}
            </ul>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">Objective (lexicographic)</summary>
              <ol className="mt-1 list-decimal pl-4">
                {sim.objective.map((x) => (
                  <li key={x}>{x.replace(/^\d+\.\s*/, "")}</li>
                ))}
              </ol>
            </details>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}
