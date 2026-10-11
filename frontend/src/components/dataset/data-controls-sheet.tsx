"use client";

import { Database } from "lucide-react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { datasetApi } from "@/lib/api/endpoints";
import type { ActiveDataset } from "@/lib/api/types";

import { DatasetPanel } from "./dataset-panel";

/** The active dataset, refetched when the data version or the clock changes. */
export function useActiveDataset(): ActiveDataset | null {
  const { config, connection } = useSystemStatus();
  const key =
    connection === "online" ? `${config?.data_version ?? 0}|${config?.simulation_time ?? ""}` : null;
  const status = useKeyedResource(key, (signal) => datasetApi.status(signal));
  return status.data?.active ?? null;
}

/** "Official scenario" rather than "Synthetic sample data — Official scenario". */
export function datasetLabel(active: ActiveDataset): string {
  return (active.label ?? active.source_name).replace(/^synthetic sample data\s*[—–-]\s*/i, "");
}

/** Dataset loading, uploads, exact time and event injection, in a right-hand drawer. */
export function DataControlsSheet({
  open,
  onOpenChange,
  children,
}: {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** A SheetTrigger, when the sheet is not controlled. */
  children?: React.ReactNode;
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {children}
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
