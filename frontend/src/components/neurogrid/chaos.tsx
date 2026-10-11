"use client";

import { CheckCircle2, FileUp, FlaskConical, Loader2, Play, Scale3d, TriangleAlert, XCircle } from "lucide-react";
import { useState } from "react";

import { SectionCard } from "@/components/shared/section-card";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { useLiveResource } from "@/hooks/use-live-resource";
import { describeError } from "@/lib/api/errors";
import { formatTime } from "@/lib/format";
import { neurogridApi, type ChaosDelta, type ChaosResult, type ImportPreview } from "@/lib/api/neurogrid";
import { cn } from "@/lib/utils";

import { Gate, Pill } from "./kit";

const ET = "America/New_York";

function show(v: unknown): string {
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return formatTime(v, ET);
  return String(v ?? "—");
}

function Deltas({ deltas }: { deltas: ChaosDelta[] }) {
  return (
    <table className="w-full text-xs">
      <thead className="text-muted-foreground">
        <tr>
          <th className="text-left font-medium">Metric</th>
          <th className="text-right font-medium">Before</th>
          <th className="text-right font-medium">After</th>
        </tr>
      </thead>
      <tbody>
        {deltas.map((d) => (
          <tr key={d.metric} className={cn("border-t", show(d.before) !== show(d.after) && "font-semibold")}>
            <td className="py-0.5">{d.metric}</td>
            <td className="text-right tabular-nums">{show(d.before)}</td>
            <td className="text-right tabular-nums">{show(d.after)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ResultView({ r }: { r: ChaosResult }) {
  return (
    <div className="space-y-3 rounded-lg border bg-card/60 p-3">
      <div className="flex flex-wrap items-center gap-2">
        {r.passed ? <Pill tone="success" icon={CheckCircle2}>PASS</Pill> : <Pill tone="critical" icon={XCircle}>FAIL</Pill>}
        <span className="font-semibold">{r.title}</span>
        <Pill tone={r.baseline_unchanged ? "success" : "critical"}>{r.baseline_unchanged ? "baseline untouched" : "BASELINE CHANGED"}</Pill>
        <span className="text-xs text-muted-foreground">
          {r.branch} · {r.duration_ms} ms · {r.run_id}
        </span>
      </div>
      <div>
        <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Injected</p>
        <ul className="list-disc pl-4 text-sm">
          {r.injected.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      </div>
      <div>
        <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Assertions (actual engine output)</p>
        <ul className="space-y-1">
          {r.assertions.map((a) => (
            <li key={a.name} className="flex items-start gap-2 text-sm">
              {a.passed ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" aria-label="pass" />
              ) : (
                <XCircle className="mt-0.5 size-4 shrink-0 text-critical" aria-label="fail" />
              )}
              <span className="min-w-0">
                {a.name}
                <span className="block text-xs text-muted-foreground">
                  expected {a.expected} · actual {a.actual}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      <Deltas deltas={r.deltas} />
      {r.alerts_new.length || r.alerts_resolved.length ? (
        <p className="text-xs text-muted-foreground">
          New alerts: {r.alerts_new.join(", ") || "none"} · resolved: {r.alerts_resolved.join(", ") || "none"}
        </p>
      ) : null}
      {r.notes.map((n) => (
        <p key={n} className="text-xs text-muted-foreground">
          {n}
        </p>
      ))}
    </div>
  );
}

export function ChaosLab() {
  const { config } = useSystemStatus();
  const scenarios = useKeyedResource(config?.dataset_loaded ? "chaos" : null, (s) => neurogridApi.chaosScenarios(s));
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<ChaosResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function run(ids: string[]) {
    setError(null);
    for (const id of ids) {
      setRunning(id);
      try {
        const r = await neurogridApi.chaosRun(id);
        setResults((prev) => [r, ...prev.filter((x) => x.scenario_id !== id)]);
      } catch (e) {
        setError(describeError(e));
        break;
      }
    }
    setRunning(null);
  }

  const passed = results.filter((r) => r.passed).length;
  return (
    <SectionCard
      title="Chaos Lab"
      icon={FlaskConical}
      description="Each scenario copies the live database into an isolated branch, injects the fault through the real ingest/workflow paths, re-runs every engine, checks assertions and deletes the branch."
      action={
        <Button size="sm" disabled={!!running || !scenarios.data} onClick={() => run((scenarios.data ?? []).map((s) => s.scenario_id))}>
          {running ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
          Run all
        </Button>
      }
    >
      <Gate resource={scenarios} feature="chaos scenarios">
        {(list) => (
          <div className="space-y-4">
            {results.length ? (
              <p className="text-sm">
                <b>{passed}</b> of {results.length} run scenarios passed.
              </p>
            ) : null}
            {error ? (
              <p role="alert" className="flex items-center gap-2 text-sm text-critical">
                <TriangleAlert className="size-4" aria-hidden />
                {error}
              </p>
            ) : null}
            <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
              <ul className="space-y-1.5">
                {list.map((s) => {
                  const r = results.find((x) => x.scenario_id === s.scenario_id);
                  return (
                    <li key={s.scenario_id} className="flex items-center gap-2 rounded-md border bg-card/60 px-2.5 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{s.title}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {s.category} · {s.injects}
                        </p>
                      </div>
                      {r ? <Pill tone={r.passed ? "success" : "critical"}>{r.passed ? "pass" : "fail"}</Pill> : null}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!!running}
                        onClick={() => run([s.scenario_id])}
                        aria-label={`Run ${s.title}`}
                      >
                        {running === s.scenario_id ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
                      </Button>
                    </li>
                  );
                })}
              </ul>
              <div className="space-y-3">
                {results.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Run a scenario to see the engine&apos;s real response. Results are not persisted; reset is automatic.</p>
                ) : (
                  results.map((r) => <ResultView key={r.run_id} r={r} />)
                )}
              </div>
            </div>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}

export function EvaluationPanel() {
  const res = useLiveResource((s) => neurogridApi.evaluation(s));
  return (
    <SectionCard
      title="Evaluation: monitoring vs reactive vs NEUROGRID"
      icon={Scale3d}
      description="Measured on the current scenario state with the same engine, candidates and rules. No invented improvements."
    >
      <Gate resource={res} feature="the evaluation">
        {(r) => (
          <div className="space-y-2">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="text-left font-medium">Metric</th>
                    <th className="text-right font-medium">Monitoring only</th>
                    <th className="text-right font-medium">Reactive</th>
                    <th className="text-right font-medium">NEUROGRID</th>
                  </tr>
                </thead>
                <tbody>
                  {r.rows.map((row) => (
                    <tr key={row.metric} className="border-t align-top">
                      <td className="py-1.5">
                        {row.metric}
                        <span className="block text-xs text-muted-foreground">{row.note}</span>
                      </td>
                      <td className="text-right tabular-nums">{String(row.monitoring_only)}</td>
                      <td className="text-right tabular-nums">{String(row.reactive)}</td>
                      <td className="text-right font-semibold tabular-nums">{String(row.neurogrid)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-muted-foreground">
              Timings: {Object.entries(r.timings_ms).map(([k, v]) => `${k.replace("_ms", "")} ${v} ms`).join(" · ")}
            </p>
          </div>
        )}
      </Gate>
    </SectionCard>
  );
}

export function DataImport() {
  const { refresh } = useSystemStatus();
  const [file, setFile] = useState<File | null>(null);
  const [advance, setAdvance] = useState(true);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function doPreview() {
    if (!file) return;
    setBusy("preview");
    setMessage(null);
    try {
      setPreview(await neurogridApi.importPreview(file, advance));
    } catch (e) {
      setPreview(null);
      setMessage({ ok: false, text: describeError(e) });
    } finally {
      setBusy(null);
    }
  }

  async function apply() {
    if (!file) return;
    setBusy("apply");
    try {
      const r = await neurogridApi.importApply(file, advance);
      setMessage({
        ok: true,
        text: `Applied: ${r.accepted} new, ${r.duplicates} duplicates. ${r.clock_note ?? "Clock unchanged."} State recomputed — no restart.`,
      });
      setPreview(null);
      refresh();
    } catch (e) {
      setMessage({ ok: false, text: describeError(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <SectionCard
      title="Supplemental event import"
      icon={FileUp}
      description="Upload an event CSV in the dataset's 8-column format. It is validated and replayed on an isolated branch first; nothing changes until you apply."
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPreview(null);
              setMessage(null);
            }}
            className="text-sm file:mr-3 file:rounded-md file:border file:bg-secondary file:px-3 file:py-1.5 file:text-sm file:text-foreground"
            aria-label="Event CSV file"
          />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={advance} onChange={(e) => setAdvance(e.target.checked)} />
            Advance the simulation clock to the latest imported event (monotonic; never backward)
          </label>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={!file || !!busy} onClick={doPreview}>
            {busy === "preview" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            Validate &amp; preview impact
          </Button>
          <Button size="sm" disabled={!file || !preview?.valid || !!busy} onClick={apply}>
            {busy === "apply" ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
            Apply events
          </Button>
        </div>
        {message ? (
          <p role="status" className={cn("rounded-md border px-3 py-2 text-sm", message.ok ? "border-success-border bg-success-soft text-success" : "border-critical-border bg-critical-soft text-critical")}>
            {message.text}
          </p>
        ) : null}
        {preview ? (
          <div className="space-y-3 rounded-lg border bg-card/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={preview.valid ? "success" : "critical"}>{preview.valid ? "valid" : "invalid"}</Pill>
              <span className="text-sm font-medium">{preview.filename}</span>
              <Pill tone="muted">{preview.received} rows</Pill>
              <Pill tone="success">{preview.accepted} new</Pill>
              <Pill tone="info">{preview.duplicates} duplicates</Pill>
              {preview.conflicting_duplicates ? <Pill tone="warning">{preview.conflicting_duplicates} conflicting (quarantined)</Pill> : null}
              {Object.keys(preview.unknown_event_types).length ? (
                <Pill tone="warning">unknown types: {Object.keys(preview.unknown_event_types).join(", ")}</Pill>
              ) : null}
            </div>
            <p className="text-sm text-muted-foreground">{preview.note}</p>
            <p className="text-sm">
              Clock {formatTime(preview.clock_before, ET)} → {formatTime(preview.clock_after, ET)}
            </p>
            {preview.errors.length ? (
              <div className="max-h-64 overflow-auto rounded border border-critical-border bg-critical-soft/40 p-2 text-xs">
                {preview.errors.map((e, i) => (
                  <pre key={i} className="whitespace-pre-wrap">{JSON.stringify(e)}</pre>
                ))}
              </div>
            ) : null}
            <Deltas deltas={preview.deltas} />
            <p className="text-xs text-muted-foreground">
              New alerts: {preview.alerts_new.join(", ") || "none"} · resolved: {preview.alerts_resolved.join(", ") || "none"}
            </p>
            <details className="text-xs">
              <summary className="cursor-pointer">Row outcomes ({preview.outcomes.length})</summary>
              <ul className="mt-1 max-h-64 space-y-0.5 overflow-auto">
                {preview.outcomes.map((o, i) => (
                  <li key={i}>
                    {String(o.event_id)} — {String(o.status)}
                    {o.visible_now === false ? " (not yet visible)" : ""}
                    {(o.warnings as string[] | undefined)?.length ? ` · ${(o.warnings as string[]).join("; ")}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}
