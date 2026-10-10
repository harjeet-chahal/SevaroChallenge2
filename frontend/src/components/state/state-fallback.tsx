"use client";

import { Loader2, TriangleAlert } from "lucide-react";

import { DataEmptyState } from "@/components/shared/data-empty-state";
import { EmptyState } from "@/components/shared/empty-state";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useOperationalState } from "./operational-state-provider";

function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn(className, "animate-spin")} />;
}

/** What a state-backed section shows before reconstructed state is available. */
export function StateFallback({
  feature,
  whenNoDataset,
  resource,
}: {
  feature: string;
  whenNoDataset: string;
  /** The resource this section waits on; defaults to the reconstructed state. */
  resource?: { error: string | null; reload: () => void };
}) {
  const { config, availability } = useSystemStatus();
  const operational = useOperationalState();
  const { error, reload } = resource ?? operational;

  if (availability === "offline" || availability === "degraded" || !config?.dataset_loaded) {
    return <DataEmptyState feature={feature} whenNoDataset={whenNoDataset} />;
  }
  if (error) {
    return (
      <EmptyState icon={TriangleAlert} title="Could not load state" description={error}>
        <Button variant="outline" size="sm" onClick={reload}>
          Retry
        </Button>
      </EmptyState>
    );
  }
  return (
    <EmptyState
      icon={Spinner}
      title="Replaying events…"
      description="Reconstructing state at the simulation time."
    />
  );
}
