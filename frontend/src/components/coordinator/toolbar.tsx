"use client";

import { Database } from "lucide-react";

import {
  DataControlsSheet,
  datasetLabel,
  useActiveDataset,
} from "@/components/dataset/data-controls-sheet";
import { PageHeader } from "@/components/shared/page-header";
import { SyntheticBadge } from "@/components/shared/status-badges";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { TimeControls } from "@/components/status/time-controls";
import { SheetTrigger } from "@/components/ui/sheet";

/** The data behind every figure, as one quiet chip that opens the data drawer. */
function DatasetChip() {
  const { config } = useSystemStatus();
  const active = useActiveDataset();
  const label = active ? datasetLabel(active) : "Data & events";

  return (
    <DataControlsSheet>
      <SheetTrigger asChild>
        <button
          type="button"
          title={`${label} · dataset & simulation controls`}
          className="inline-flex h-10 max-w-full items-center gap-2.5 rounded-[10px] border border-border bg-card px-3.5 text-sm text-foreground-2 hover:border-border-strong hover:text-foreground"
        >
          <Database className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="truncate">
            Dataset · {label}
            {config ? (
              <span className="font-mono text-caption text-muted-foreground">
                {" "}
                · data v{config.data_version}
              </span>
            ) : null}
          </span>
          {active?.synthetic ? <SyntheticBadge className="max-sm:hidden" /> : null}
        </button>
      </SheetTrigger>
    </DataControlsSheet>
  );
}

export function CoordinatorToolbar() {
  const { config } = useSystemStatus();
  return (
    <PageHeader
      title="Command center"
      description="The single most urgent problem first, then every hospital's coverage over the next 90 minutes and what you have set in motion. Every figure comes from the backend on the simulation clock."
      actions={
        config?.dataset_loaded ? (
          // The sidebar's monitor card has the clock controls; phones get them here.
          <TimeControls variant="toolbar" className="min-[900px]:hidden" />
        ) : null
      }
    >
      {config?.dataset_loaded ? (
        <div className="pt-2">
          <DatasetChip />
        </div>
      ) : null}
    </PageHeader>
  );
}
