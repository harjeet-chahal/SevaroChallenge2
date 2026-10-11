"use client";

import {
  ChevronDown,
  Clock,
  Database,
  FastForward,
  FileUp,
  FlaskConical,
  Loader2,
  RotateCcw,
  Send,
} from "lucide-react";
import { useState } from "react";

import { SyntheticBadge } from "@/components/shared/status-badges";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { ApiError } from "@/lib/api/client";
import { datasetApi, eventsApi, simulationApi } from "@/lib/api/endpoints";
import { describeError } from "@/lib/api/errors";
import type {
  DatasetImportReport,
  EventIngestOutcome,
  EventIngestResult,
  ImportIssue,
} from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { ImportReportView, IngestResultView, IssueList } from "./import-report-view";

type ActionResult =
  | { kind: "report"; report: DatasetImportReport }
  | {
      kind: "ingest";
      result?: EventIngestResult;
      rejected?: EventIngestOutcome[];
      message?: string;
    }
  | { kind: "issues"; message: string; issues: ImportIssue[] }
  | { kind: "message"; ok: boolean; message: string };

const INJECT_TEMPLATE = `{
  "event_id": "",
  "event_type": "",
  "event_time": "",
  "consult_id": null,
  "physician_id": null,
  "hospital_id": null
}`;

function isReport(value: unknown): value is DatasetImportReport {
  return typeof value === "object" && value !== null && "import_id" in value && "issues" in value;
}

function toResult(error: unknown): ActionResult {
  if (error instanceof ApiError) {
    const details = error.details as Record<string, unknown> | undefined;
    if (isReport(details)) return { kind: "report", report: details };
    if (details && Array.isArray(details.outcomes)) {
      return {
        kind: "ingest",
        rejected: details.outcomes as EventIngestOutcome[],
        message: error.message,
      };
    }
    if (details && Array.isArray(details.issues)) {
      return { kind: "issues", message: error.message, issues: details.issues as ImportIssue[] };
    }
  }
  return { kind: "message", ok: false, message: describeError(error) };
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium font-mono tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * Developer / judging controls. Every number shown here comes from the backend.
 * ``plain`` renders only the controls (inside the data drawer); the default renders a
 * collapsible panel (used inline when no dataset is loaded yet).
 */
export function DatasetPanel({
  className,
  variant = "panel",
}: {
  className?: string;
  variant?: "panel" | "plain";
}) {
  const { config, connection, refresh } = useSystemStatus();
  const online = connection === "online";
  const key = online ? `${config?.data_version ?? 0}|${config?.simulation_time ?? ""}` : null;
  const status = useKeyedResource(key, (signal) => datasetApi.status(signal));
  const samples = useKeyedResource(online ? "samples" : null, (signal) =>
    datasetApi.samples(signal),
  );
  const clock = useKeyedResource(config?.dataset_loaded ? key : null, (signal) =>
    simulationApi.clock(signal),
  );

  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<ActionResult | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [referenceTime, setReferenceTime] = useState("");
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [setTimeValue, setSetTimeValue] = useState("");
  const [injectJson, setInjectJson] = useState(INJECT_TEMPLATE);
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  // Open until a dataset is loaded (or while showing a fresh result); otherwise compact.
  const open = userOpen ?? (!config?.dataset_loaded || result !== null);

  async function run(label: string, action: () => Promise<ActionResult | null>) {
    setBusy(label);
    try {
      const next = await action();
      if (next) setResult(next);
    } catch (error) {
      setResult(toResult(error));
    } finally {
      setBusy(null);
      refresh();
      status.reload();
      clock.reload();
    }
  }

  const active = status.data?.active ?? null;
  const lastFailed =
    status.data?.last_attempt?.status === "failed" ? status.data.last_attempt : null;
  const disabled = !online || busy !== null;

  const spinner = (label: string) =>
    busy === label ? <Loader2 className="animate-spin" aria-hidden /> : null;

  const controls = (
    <div className={cn(variant === "panel" && "border-t p-4")}>
      <div className={cn("grid gap-6", variant === "panel" && "lg:grid-cols-2")}>
        <div className="space-y-4">
          <div className="space-y-2">
            <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
              Active dataset {active?.synthetic ? <SyntheticBadge /> : null}
            </h3>
            {active ? (
              <dl className="space-y-1 rounded-lg border bg-muted/30 p-3">
                <Stat label="Label" value={active.label ?? active.source_name} />
                <Stat label="Imported" value={formatDateTime(active.imported_at)} />
                <Stat label="Hospitals" value={active.counts.hospitals ?? 0} />
                <Stat label="Physicians" value={active.counts.physicians ?? 0} />
                <Stat
                  label="Events (incl. live)"
                  value={`${active.counts.events ?? 0} (${active.live_events} live)`}
                />
                <Stat label="Rejected rows" value={active.rejected_events} />
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">
                {online ? "No dataset loaded." : "Backend unreachable."}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <p className="text-sm font-medium">Load a bundled synthetic sample</p>
            <div className="flex flex-wrap gap-2">
              {(samples.data ?? []).map((sample) => (
                <Button
                  key={sample.name}
                  onClick={() =>
                    run(`sample:${sample.name}`, async () => ({
                      kind: "report",
                      report: await datasetApi.loadSample(sample.name),
                    }))
                  }
                  disabled={disabled}
                  variant="secondary"
                  title={sample.label}
                >
                  {spinner(`sample:${sample.name}`) ?? <FlaskConical aria-hidden />}
                  Load {sample.name.replace(/^synthetic_/, "").replaceAll("_", " ")} sample
                </Button>
              ))}
            </div>
          </div>

          <form
            className="space-y-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (files.length === 0) return;
              void run("upload", async () => ({
                kind: "report",
                report: await datasetApi.upload(files, referenceTime.trim() || undefined),
              }));
            }}
          >
            <label className="block text-sm font-medium" htmlFor="dataset-files">
              Upload dataset (one ZIP or the CSV files)
            </label>
            <Input
              id="dataset-files"
              type="file"
              multiple
              accept=".zip,.csv,.json"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              disabled={disabled}
            />
            <Input
              aria-label="Reference time override (optional)"
              placeholder="Reference time override, e.g. 2030-05-14T17:30:00-04:00 (optional)"
              value={referenceTime}
              onChange={(e) => setReferenceTime(e.target.value)}
              disabled={disabled}
            />
            <Button type="submit" disabled={disabled || files.length === 0}>
              {spinner("upload") ?? <FileUp aria-hidden />}
              Import {files.length ? `${files.length} file(s)` : ""}
            </Button>
          </form>
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Clock className="size-4 text-primary" aria-hidden /> Simulation clock
            </h3>
            {clock.data ? (
              <dl className="space-y-1 rounded-lg border bg-muted/30 p-3">
                <Stat
                  label="Simulation time"
                  value={
                    clock.data.current_time ? formatDateTime(clock.data.current_time) : "Not set"
                  }
                />
                <Stat
                  label="Reference time"
                  value={
                    clock.data.reference_time
                      ? `${formatDateTime(clock.data.reference_time)} (${clock.data.reference_source})`
                      : "—"
                  }
                />
                <Stat label="Events not yet ingested" value={clock.data.events_pending_ingestion} />
                <Stat
                  label="Server wall clock (not used)"
                  value={formatDateTime(clock.data.server_time)}
                />
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">
                The clock starts at the dataset&apos;s reference time once a dataset is loaded.
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {[1, 5, 15, 60].map((minutes) => (
              <Button
                key={minutes}
                variant="outline"
                size="sm"
                disabled={disabled || !config?.dataset_loaded}
                onClick={() =>
                  run(`adv${minutes}`, async () => {
                    await simulationApi.advance(minutes);
                    return null;
                  })
                }
              >
                {spinner(`adv${minutes}`) ?? <FastForward aria-hidden />}+{minutes} min
              </Button>
            ))}
            <Button
              variant="outline"
              size="sm"
              disabled={disabled || !config?.dataset_loaded}
              onClick={() =>
                run("reset", async () => {
                  await simulationApi.reset();
                  return null;
                })
              }
            >
              {spinner("reset") ?? <RotateCcw aria-hidden />}
              Reset to reference
            </Button>
          </div>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!setTimeValue.trim()) return;
              void run("set", async () => {
                await simulationApi.setTime(setTimeValue.trim());
                return { kind: "message", ok: true, message: "Simulation time set." };
              });
            }}
          >
            <Input
              aria-label="Set simulation time"
              placeholder={clock.data?.current_time ?? "ISO-8601 with offset"}
              value={setTimeValue}
              onChange={(e) => setSetTimeValue(e.target.value)}
              disabled={disabled || !config?.dataset_loaded}
            />
            <Button type="submit" variant="outline" disabled={disabled || !setTimeValue.trim()}>
              Set time
            </Button>
          </form>

          <details className="rounded-lg border p-3">
            <summary className="cursor-pointer text-sm font-semibold">Inject events</summary>
            <div className="mt-3 space-y-3">
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!csvFile) return;
                  void run("csv", async () => ({
                    kind: "ingest",
                    result: await eventsApi.appendCsv(csvFile),
                  }));
                }}
              >
                <label className="block text-sm font-medium" htmlFor="event-csv">
                  Append event rows (same columns as event_stream.csv)
                </label>
                <Input
                  id="event-csv"
                  type="file"
                  accept=".csv"
                  onChange={(e) => setCsvFile(e.target.files?.[0] ?? null)}
                  disabled={disabled || !config?.dataset_loaded}
                />
                <Button type="submit" size="sm" disabled={disabled || !csvFile}>
                  {spinner("csv") ?? <FileUp aria-hidden />}
                  Append CSV
                </Button>
              </form>
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  let parsed: unknown;
                  try {
                    parsed = JSON.parse(injectJson);
                    setJsonError(null);
                  } catch {
                    setJsonError("Not valid JSON.");
                    return;
                  }
                  void run("json", async () => ({
                    kind: "ingest",
                    result: await eventsApi.inject(parsed),
                  }));
                }}
              >
                <label className="block text-sm font-medium" htmlFor="event-json">
                  Or JSON (one event or a list). ingested_at defaults to the simulation time.
                </label>
                <Textarea
                  id="event-json"
                  className="font-mono text-xs"
                  rows={8}
                  value={injectJson}
                  onChange={(e) => setInjectJson(e.target.value)}
                  disabled={disabled || !config?.dataset_loaded}
                />
                {jsonError ? <p className="text-xs text-critical-ink">{jsonError}</p> : null}
                <Button type="submit" size="sm" disabled={disabled || !config?.dataset_loaded}>
                  {spinner("json") ?? <Send aria-hidden />}
                  Inject
                </Button>
              </form>
            </div>
          </details>
        </div>
      </div>

      <div className="mt-4 space-y-3" aria-live="polite">
        {result?.kind === "report" ? <ImportReportView report={result.report} /> : null}
        {result?.kind === "ingest" ? (
          <IngestResultView
            result={result.result}
            rejected={result.rejected}
            message={result.message}
          />
        ) : null}
        {result?.kind === "issues" ? (
          <div className="rounded-lg border border-critical-border bg-critical-soft/40 p-3">
            <p className="text-sm font-semibold text-critical-ink">{result.message}</p>
            <IssueList issues={result.issues} />
          </div>
        ) : null}
        {result?.kind === "message" ? (
          <p className={result.ok ? "text-sm text-success-ink" : "text-sm text-critical-ink"}>
            {result.message}
          </p>
        ) : null}
        {!result && lastFailed ? (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Last import attempt</p>
            <ImportReportView report={lastFailed} />
          </div>
        ) : null}
      </div>
    </div>
  );

  if (variant === "plain") return controls;

  return (
    <section
      aria-labelledby="dataset-panel-heading"
      className={cn("rounded-xl border bg-card", className)}
    >
      <details open={open} onToggle={(e) => setUserOpen(e.currentTarget.open)} className="group">
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 rounded-xl p-4 outline-none focus-visible:ring-3 focus-visible:ring-ring/50">
          <Database className="size-4 text-primary" aria-hidden />
          <h2 id="dataset-panel-heading" className="font-semibold">
            Dataset &amp; simulation controls
          </h2>
          {active?.synthetic ? <SyntheticBadge /> : null}
          <span className="text-sm text-muted-foreground">
            {active
              ? `${active.label ?? active.source_name}${
                  clock.data?.events_pending_ingestion
                    ? ` · ${clock.data.events_pending_ingestion} event(s) not yet ingested`
                    : ""
                }`
              : "No dataset loaded: load the sample or upload one"}
          </span>
          <ChevronDown
            className="ml-auto size-4 text-muted-foreground transition-transform group-open:rotate-180"
            aria-hidden
          />
        </summary>
        {controls}
      </details>
    </section>
  );
}
