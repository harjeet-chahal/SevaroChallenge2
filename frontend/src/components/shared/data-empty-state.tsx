"use client";

import { CloudOff, Database, Hourglass, Loader2, TriangleAlert } from "lucide-react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { EmptyState } from "./empty-state";

function SpinningLoader({ className }: { className?: string }) {
  return <Loader2 className={cn(className, "animate-spin")} />;
}

/**
 * The single place that decides what an empty data section says, based on real
 * backend state. Sections describe *what* they will show; this decides *why* it's empty.
 */
export function DataEmptyState({
  whenNoDataset,
  feature,
  compact,
}: {
  /** Explains what will appear here once a dataset is loaded. */
  whenNoDataset: string;
  /** Name of the backend capability this section is waiting on, e.g. "alert detection". */
  feature: string;
  compact?: boolean;
}) {
  const { availability, apiBaseUrl, error, refresh } = useSystemStatus();

  switch (availability) {
    case "checking":
      return (
        <EmptyState
          compact={compact}
          icon={SpinningLoader}
          title="Connecting to backend…"
          description="Checking API availability."
        />
      );
    case "offline":
      return (
        <EmptyState
          compact={compact}
          icon={CloudOff}
          title="Backend unreachable"
          description={
            <>
              Can&apos;t reach the API at{" "}
              <code className="rounded bg-inset px-1 py-0.5 font-mono text-xs">{apiBaseUrl}</code>. Data
              will appear once the connection is restored.
            </>
          }
        >
          <Button variant="outline" size="sm" onClick={refresh}>
            Retry
          </Button>
        </EmptyState>
      );
    case "degraded":
      return (
        <EmptyState
          compact={compact}
          icon={TriangleAlert}
          title="Backend degraded"
          description={error ?? "The API responded but a dependency check failed."}
        />
      );
    case "no-dataset":
      return (
        <EmptyState
          compact={compact}
          icon={Database}
          title="No dataset loaded"
          description={whenNoDataset}
        />
      );
    case "awaiting-feature":
      return (
        <EmptyState
          compact={compact}
          icon={Hourglass}
          title="Not connected yet"
          description={`A dataset is loaded, but the ${feature} API is not implemented yet.`}
        />
      );
  }
}
