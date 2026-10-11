"use client";

import { Database, Loader2, RotateCcw } from "lucide-react";

import { DatasetPanel } from "@/components/dataset/dataset-panel";
import { PageHeader } from "@/components/shared/page-header";
import { SyntheticBadge } from "@/components/shared/status-badges";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Feedback } from "@/components/workflow/feedback";
import { useAction } from "@/components/workflow/use-action";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { datasetApi, simulationApi } from "@/lib/api/endpoints";

const STEPS = [1, 5, 15, 60];

/** Demo clock controls: always one click away, visually quiet. */
function TimeControls() {
  const { config, connection } = useSystemStatus();
  const { pending, feedback, run } = useAction();
  const disabled = connection !== "online" || !config?.dataset_loaded || pending !== null;

  return (
    <div className="flex flex-col items-end gap-1">
      <div
        role="group"
        aria-label="Advance simulation time"
        className="flex items-center gap-0.5 rounded-lg border bg-card p-0.5 shadow-xs"
      >
        <span className="px-2 text-xs font-medium text-muted-foreground max-sm:sr-only">
          Advance
        </span>
        {STEPS.map((minutes) => (
          <Button
            key={minutes}
            variant="ghost"
            size="sm"
            disabled={disabled}
            aria-label={`Advance ${minutes} minute${minutes === 1 ? "" : "s"}`}
            onClick={() =>
              run(`adv${minutes}`, () => simulationApi.advance(minutes).then(() => undefined))
            }
          >
            {pending === `adv${minutes}` ? <Loader2 className="animate-spin" aria-hidden /> : null}+
            {minutes}m
          </Button>
        ))}
        <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled}
          title="Reset to the dataset reference time"
          onClick={() => run("reset", () => simulationApi.reset().then(() => undefined))}
        >
          {pending === "reset" ? (
            <Loader2 className="animate-spin" aria-hidden />
          ) : (
            <RotateCcw aria-hidden />
          )}
          Reset
        </Button>
      </div>
      {feedback?.tone === "error" ? <Feedback feedback={feedback} /> : null}
    </div>
  );
}

/** Dataset loading, uploads, exact time and event injection — tucked into a drawer. */
function DataControls() {
  const { config, connection } = useSystemStatus();
  const online = connection === "online";
  const key = online ? `${config?.data_version ?? 0}|${config?.simulation_time ?? ""}` : null;
  const status = useKeyedResource(key, (signal) => datasetApi.status(signal));
  const active = status.data?.active ?? null;
  // The synthetic badge already says it; don't repeat it in the label.
  const label = active
    ? (active.label ?? active.source_name).replace(/^synthetic sample data\s*[—–-]\s*/i, "")
    : "Data & events";

  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          className="h-9 max-w-80 shadow-xs"
          title={`${label} · dataset & simulation controls`}
        >
          <Database aria-hidden />
          <span className="truncate">{label}</span>
          {active?.synthetic ? <SyntheticBadge className="max-sm:hidden" /> : null}
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <Database className="size-4 text-primary" aria-hidden />
            Dataset &amp; simulation controls
          </SheetTitle>
          <SheetDescription>
            Load a sample or the judging dataset, set the simulation time, or inject events.
          </SheetDescription>
        </SheetHeader>
        <SheetBody>
          <DatasetPanel variant="plain" />
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}

export function CoordinatorToolbar() {
  const { config } = useSystemStatus();
  return (
    <PageHeader
      title="Network operations"
      description="What needs attention now, what is coming in the next 90 minutes, and what you have set in motion."
      actions={
        config?.dataset_loaded ? (
          <>
            <TimeControls />
            <DataControls />
          </>
        ) : null
      }
    />
  );
}
