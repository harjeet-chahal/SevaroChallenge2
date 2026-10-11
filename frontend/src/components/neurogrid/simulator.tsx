"use client";

import { BadgeCheck, Ban, FlaskRound, Sparkles, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useLiveResource } from "@/hooks/use-live-resource";
import { ApiError } from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";
import { formatHm, zoneAbbr } from "@/lib/format";
import { neurogridApi, type RescueOption, type RescueSimulation } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { Gate, Pill } from "./kit";

const ET = "America/New_York";

const KIND_LABEL: Record<RescueOption["kind"], string> = {
  do_nothing: "No action",
  escalation: "Escalation",
  reassignment: "Consult reassignment",
  split_shift: "Off-duty extra shift",
  shift_extension: "Shift extension",
  combination: "Coordinated plan",
};

function proposable(o: RescueOption) {
  return Boolean(o.proposal && o.feasible && !o.simulation_only && o.kind !== "do_nothing");
}

function etTime(iso: string | null) {
  return iso ? `${formatHm(iso, ET)} ${zoneAbbr(iso, ET)}` : "—";
}

function afterTone(before: number, after: number) {
  if (after <= 0) return "text-success-ink";
  return after >= before ? "text-critical-ink" : "text-warning-ink";
}

/** Before → after bar: the hatched track is the gap with no action; the solid fill is what remains. */
function GapBar({ before, after }: { before: number; after: number }) {
  const frac = before > 0 ? Math.min(1, Math.max(0, after / before)) : 0;
  return (
    <div
      role="img"
      aria-label={`Target gap ${before} to ${after} physician-minutes`}
      className={cn("relative h-2.5 rounded-full", before > 0 ? "hatch-critical" : "bg-selected")}
    >
      <div
        className="absolute inset-y-0 left-0 rounded-full bg-critical transition-[width] duration-500"
        style={{ width: `${frac * 100}%` }}
      />
    </div>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <span>{label}</span>
      <span className="font-mono text-foreground tabular-nums">{children}</span>
    </>
  );
}

function OptionCard({ o, onPropose, busy }: { o: RescueOption; onPropose: (o: RescueOption) => void; busy: boolean }) {
  const out = o.outcome;
  const baseline = o.kind === "do_nothing";
  const infeasible = !o.feasible && !o.simulation_only;
  const note = o.simulation_only
    ? "Evaluated for comparison only — it can never be proposed."
    : infeasible
      ? "Fails a hard eligibility rule; ranked after feasible options."
      : baseline
        ? "What happens if no one acts."
        : null;
  return (
    <li
      className={cn(
        "flex flex-col gap-3.5 rounded-[14px] p-[18px]",
        o.recommended
          ? "border-[1.5px] border-primary/70 bg-card"
          : baseline
            ? "border border-dashed border-border-strong"
            : "border bg-card",
        (infeasible || o.simulation_only) && "opacity-85",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <span className="font-mono text-xl font-semibold text-muted-foreground tabular-nums">{o.rank ?? "–"}</span>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-[15.5px] font-semibold">{KIND_LABEL[o.kind]}</span>
            <span className="text-caption text-muted-foreground">{o.label}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {o.recommended ? (
            <Pill tone="primary" icon={Sparkles} className="rounded-sm tracking-[0.04em]">
              Recommended
            </Pill>
          ) : null}
          {o.simulation_only ? (
            <Pill tone="info" icon={FlaskRound} className="rounded-sm tracking-[0.04em]">
              Simulation only
            </Pill>
          ) : null}
          {infeasible ? (
            <Pill tone="critical" icon={Ban} className="rounded-sm tracking-[0.04em]">
              Infeasible
            </Pill>
          ) : null}
          {baseline ? (
            <Pill tone="muted" className="rounded-sm tracking-[0.04em]">
              Baseline
            </Pill>
          ) : null}
          {o.requires_approval && o.feasible && !o.simulation_only ? <Pill tone="muted">needs clinical-lead approval</Pill> : null}
        </div>
      </div>
      {out ? (
        <div className="grid grid-cols-1 items-center gap-4 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-1.5">
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Target gap · phys-min</span>
              <span className="font-mono text-foreground">
                {out.target_deficit_before} →{" "}
                <b className={afterTone(out.target_deficit_before, out.target_deficit_after)}>{out.target_deficit_after}</b>
              </span>
            </div>
            <GapBar before={out.target_deficit_before} after={out.target_deficit_after} />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>Network gap</span>
              <span className="font-mono text-foreground-2">
                {out.network_deficit_before} → {out.network_deficit_after}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
            <Stat label="New gaps elsewhere">
              {out.new_shortfall_hospital_ids.length ? out.new_shortfall_hospital_ids.join(", ") : 0}
            </Stat>
            <Stat label="Single points">
              {out.single_points_before} → {out.single_points_after}
            </Stat>
            <Stat label="Contacted">{o.physician_ids.length}</Stat>
            <Stat label="Active by">{etTime(out.activation_at)}</Stat>
          </div>
        </div>
      ) : null}
      {o.blocking_reasons.length ? (
        <div className="flex flex-wrap gap-1.5">
          {o.blocking_reasons.map((b) => (
            <span key={b} className="rounded-sm border border-border-strong px-2 py-0.5 text-label text-critical-ink">
              ✕ {b}
            </span>
          ))}
        </div>
      ) : null}
      {note ? <p className="text-caption text-foreground-2">{note}</p> : null}
      {o.why.length ? (
        <details open={o.recommended} className="text-xs">
          <summary className="cursor-pointer font-medium text-foreground-2">Why this option?</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-muted-foreground">
            {o.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
            {o.uncertainty.map((w) => (
              <li key={w}>Uncertainty: {w}</li>
            ))}
          </ul>
          <p className="mt-1 font-mono text-faint-foreground">
            key [{o.lexicographic_key.map((k) => (k > 1e8 ? "∞" : k)).join(", ")}]
          </p>
        </details>
      ) : null}
      {proposable(o) ? (
        <div className="flex justify-end">
          <Button size="sm" variant={o.recommended ? "default" : "outline"} disabled={busy} onClick={() => onPropose(o)}>
            <Workflow className="size-4" aria-hidden />
            Create rescue contract
          </Button>
        </div>
      ) : null}
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
  const go = (id: string) => router.replace(id ? `/simulator?hospital=${id}` : "/simulator");
  const cards = [
    { id: "", label: "Most urgent", sub: "projected shortfall" },
    ...(lsm.data?.items ?? []).map((i) => ({
      id: i.hospital_id,
      label: i.hospital_name,
      sub:
        i.phase === "no_candidate"
          ? "no eligible candidate"
          : `short ${formatHm(i.shortfall_at, i.timezone)} ${zoneAbbr(i.shortfall_at, i.timezone)}`,
    })),
  ];
  return (
    <div className="flex flex-col gap-2.5">
      <div role="radiogroup" aria-label="Rescue target" className="flex flex-wrap gap-2">
        {cards.map((c) => {
          const on = current === c.id;
          return (
            <button
              key={c.id || "auto"}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => go(c.id)}
              className={cn(
                "flex flex-col items-start gap-0.5 rounded-[10px] border px-3.5 py-2.5 text-left text-sm transition-colors",
                on ? "border-primary/70 bg-selected" : "bg-card-subtle hover:bg-hover",
              )}
            >
              <span className="font-semibold">{c.label}</span>
              <span className="text-xs text-muted-foreground">{c.sub}</span>
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-2 text-caption text-muted-foreground">
        <label htmlFor="sim-target">Any hospital</label>
        <select
          id="sim-target"
          value={current}
          onChange={(e) => go(e.target.value)}
          className="rounded-md border border-border-strong bg-card px-2 py-1 text-foreground"
        >
          <option value="">Most urgent projected shortfall</option>
          {hospitals.map((h) => (
            <option key={h.hospital_id} value={h.hospital_id}>
              {h.hospital_name} ({h.status})
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function RecommendedRail({
  sim,
  result,
}: {
  sim: RescueSimulation;
  result: { ok: boolean; text: string } | null;
}) {
  const rec = sim.options.find((o) => o.recommended);
  const out = rec?.outcome;
  const w = rec?.workload as Record<string, number | undefined> | null | undefined;
  return (
    <div className="flex flex-col gap-3.5 min-[1100px]:sticky min-[1100px]:top-24">
      {rec ? (
        <div className="flex flex-col gap-3 rounded-[14px] border bg-card p-[18px]">
          <span className="text-[11px] font-semibold tracking-[0.12em] text-muted-foreground uppercase">
            Recommended · before → after
          </span>
          {out ? (
            <div className="flex flex-wrap items-baseline gap-2.5">
              <span className="font-mono text-[40px] font-semibold text-foreground-2 line-through decoration-critical">
                {out.target_deficit_before}
              </span>
              <span className="text-[22px] text-muted-foreground">→</span>
              <span className={cn("font-mono text-[52px] leading-none font-semibold", afterTone(out.target_deficit_before, out.target_deficit_after))}>
                {out.target_deficit_after}
              </span>
              <span className="text-[13px] text-muted-foreground">phys-min gap</span>
            </div>
          ) : null}
          <span className="text-[13.5px] leading-normal">
            {KIND_LABEL[rec.kind]} · {rec.label}
          </span>
        </div>
      ) : null}
      {w && w.unrestricted_routed_to_joiner !== undefined ? (
        <div className="flex flex-col gap-3 rounded-[14px] border bg-card-subtle p-[18px]">
          <span className="text-sm font-semibold">Load Guardian · incoming physician</span>
          <div className="grid grid-cols-2 gap-2.5">
            <div className="flex flex-col gap-1 rounded-[10px] bg-inset p-3">
              <span className="text-xs text-muted-foreground">Unprotected</span>
              <span className="font-mono text-[26px] font-semibold">{String(w.unrestricted_routed_to_joiner)}</span>
              <span className="text-label text-muted-foreground">modeled consults on arrival</span>
            </div>
            <div className="flex flex-col gap-1 rounded-[10px] border border-primary/35 bg-primary/10 p-3">
              <span className="text-xs text-primary-ink">Protected</span>
              <span className="font-mono text-[26px] font-semibold">{String(w.protected_routed_to_joiner)}</span>
              <span className="text-label text-foreground-2">{String(w.protected_elsewhere ?? 0)} routed outside the gap</span>
            </div>
          </div>
        </div>
      ) : null}
      {result ? (
        <div
          role="status"
          className={cn(
            "flex flex-col gap-2 rounded-xl border px-4 py-3.5",
            result.ok ? "border-success-border bg-success-soft" : "border-critical-border bg-critical-soft",
          )}
        >
          <span className={cn("flex items-center gap-2 text-sm font-semibold", result.ok ? "text-success-ink" : "text-critical-ink")}>
            {result.ok ? <BadgeCheck className="size-4" aria-hidden /> : <Ban className="size-4" aria-hidden />}
            {result.text}
          </span>
          {result.ok ? (
            <>
              <span className="text-caption text-foreground-2">Sent to the clinical lead for approval.</span>
              <Link href="/contracts" className="text-[13px] text-primary-ink hover:underline">
                Open Rescue Contracts →
              </Link>
            </>
          ) : null}
        </div>
      ) : null}
      <p className="text-xs leading-normal text-muted-foreground">
        Projections only. Nothing changes until the clinical lead approves a rescue contract.
      </p>
      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">Objective (lexicographic)</summary>
        <ol className="mt-1 list-decimal pl-4">
          {sim.objective.map((x) => (
            <li key={x}>{x.replace(/^\d+\.\s*/, "")}</li>
          ))}
        </ol>
      </details>
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
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  async function propose(o: RescueOption) {
    setBusy(true);
    setResult(null);
    try {
      const iv = await neurogridApi.propose(o.proposal ?? {});
      setResult({ ok: true, text: `${iv.id} created — ${iv.status.replaceAll("_", " ")}. Nobody has been contacted.` });
    } catch (e) {
      const details = e instanceof ApiError ? (e.details as { blocking_reasons?: string[] } | null) : null;
      setResult({ ok: false, text: [describeError(e), ...(details?.blocking_reasons ?? [])].join(" ") });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <TargetPicker />
      <Gate resource={res} feature="the rescue simulator">
        {(sim) => (
          <div className="grid grid-cols-1 items-start gap-4 min-[1100px]:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)]">
            <div className="flex flex-col gap-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-[17px] font-semibold">
                  {sim.options.length} options, ranked <span className="font-normal text-muted-foreground">· {sim.target_label}</span>
                </h2>
                <span className="text-xs text-muted-foreground">
                  hard-rule violations last → target gap → new gaps → network gap → joiner overload → contacted → activation
                </span>
              </div>
              <ul className="flex flex-col gap-2.5">
                {sim.options.map((o) => (
                  <OptionCard key={o.option_id} o={o} onPropose={propose} busy={busy} />
                ))}
              </ul>
            </div>
            <RecommendedRail sim={sim} result={result} />
          </div>
        )}
      </Gate>
    </div>
  );
}
