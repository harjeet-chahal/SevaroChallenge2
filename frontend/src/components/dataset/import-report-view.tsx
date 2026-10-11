import { CircleAlert, CircleCheck, Info, OctagonAlert } from "lucide-react";

import type {
  DatasetImportReport,
  EventIngestResult,
  FieldIssue,
  ImportIssue,
  IssueSeverity,
} from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const SEVERITY: Record<IssueSeverity, { icon: typeof Info; tone: string; label: string }> = {
  error: { icon: OctagonAlert, tone: "text-critical-ink", label: "Error" },
  warning: { icon: CircleAlert, tone: "text-warning-ink", label: "Warning" },
  info: { icon: Info, tone: "text-info-ink", label: "Info" },
};

function IssueRow({ issue }: { issue: ImportIssue }) {
  const { icon: Icon, tone, label } = SEVERITY[issue.severity];
  const where = [issue.file, issue.row ? `row ${issue.row}` : null, issue.column]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="flex gap-2 py-1.5">
      <Icon className={cn("mt-0.5 size-4 shrink-0", tone)} aria-label={label} />
      <div className="min-w-0 text-sm">
        <p className="break-words">
          {where ? <span className="font-medium">{where}: </span> : null}
          {issue.message}
        </p>
        {issue.hint ? <p className="text-xs text-muted-foreground">Fix: {issue.hint}</p> : null}
      </div>
    </li>
  );
}

const ORDER: IssueSeverity[] = ["error", "warning", "info"];

export function IssueList({ issues }: { issues: ImportIssue[] }) {
  const ordered = [...issues].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity));
  if (ordered.length === 0) return null;
  return (
    <ul className="mt-2 max-h-72 divide-y overflow-y-auto pr-1">
      {ordered.map((issue, i) => (
        <IssueRow key={`${issue.code}-${i}`} issue={issue} />
      ))}
    </ul>
  );
}

export function ImportReportView({ report }: { report: DatasetImportReport }) {
  const ok = report.status === "completed";
  const errors = report.issues.filter((i) => i.severity === "error").length;
  const warnings = report.issues.filter((i) => i.severity === "warning").length;

  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        ok
          ? "border-success-border bg-success-soft/40"
          : "border-critical-border bg-critical-soft/40",
      )}
    >
      <p
        className={cn(
          "flex items-center gap-2 text-sm font-semibold",
          ok ? "text-success-ink" : "text-critical-ink",
        )}
      >
        {ok ? (
          <CircleCheck className="size-4" aria-hidden />
        ) : (
          <OctagonAlert className="size-4" aria-hidden />
        )}
        {ok ? "Import succeeded" : "Import failed — the active dataset was not changed"}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        {report.source_name} · {errors} error(s), {warnings} warning(s)
        {report.reference_time
          ? ` · reference ${formatDateTime(report.reference_time)} (${report.reference_source})`
          : ""}
      </p>
      {ok && Object.keys(report.counts).length > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          {Object.entries(report.counts)
            .map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`)
            .join(" · ")}
        </p>
      ) : null}
      <IssueList issues={report.issues} />
      {report.issues_truncated > 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">
          {report.issues_truncated} more issue(s) not shown.
        </p>
      ) : null}
      {report.column_mappings.length > 0 ? (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer font-medium text-muted-foreground">
            Column mapping used ({report.column_mappings.length} files)
          </summary>
          <ul className="mt-1 space-y-1">
            {report.column_mappings.map((m) => (
              <li key={m.file} className="break-words">
                <span className="font-medium">{m.file}</span>:{" "}
                {Object.entries(m.mapped)
                  .map(([field, header]) => (field === header ? field : `${field} ← "${header}"`))
                  .join(", ")}
                {m.unmapped_headers.length
                  ? ` · kept as attributes: ${m.unmapped_headers.join(", ")}`
                  : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function FieldErrors({ errors }: { errors: FieldIssue[] }) {
  return (
    <ul className="ml-5 list-disc text-xs">
      {errors.map((e, i) => (
        <li key={i}>{e.message}</li>
      ))}
    </ul>
  );
}

export function IngestResultView({
  result,
  rejected,
  message,
}: {
  result?: EventIngestResult;
  rejected?: { index: number; event_id: string | null; errors: FieldIssue[] }[];
  message?: string;
}) {
  if (rejected && rejected.length > 0) {
    return (
      <div className="rounded-lg border border-critical-border bg-critical-soft/40 p-3 text-sm">
        <p className="font-semibold text-critical-ink">
          {message ?? "Events rejected; nothing was stored."}
        </p>
        <ul className="mt-2 space-y-1">
          {rejected.map((r) => (
            <li key={r.index}>
              <span className="font-medium">
                #{r.index} {r.event_id ?? "(no id)"}
              </span>
              <FieldErrors errors={r.errors} />
            </li>
          ))}
        </ul>
      </div>
    );
  }
  if (!result) return null;
  return (
    <div className="rounded-lg border border-success-border bg-success-soft/40 p-3 text-sm">
      <p className="font-semibold text-success-ink">
        {result.accepted} event(s) accepted, {result.duplicates} duplicate(s)
      </p>
      <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
        {result.outcomes.map((o) => (
          <li key={o.index}>
            {o.event_id}: {o.status}
            {o.visible_now === false
              ? " (not visible until the clock reaches its ingested_at)"
              : ""}
            {o.warnings.length ? ` — ${o.warnings.join("; ")}` : ""}
          </li>
        ))}
      </ul>
    </div>
  );
}
