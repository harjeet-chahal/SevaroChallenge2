import type { Metadata } from "next";

import { DataImport } from "@/components/neurogrid/chaos";
import { DatasetPanel } from "@/components/dataset/dataset-panel";
import { PageHeader } from "@/components/shared/page-header";
import { SimulationStatus } from "@/components/status/simulation-status";

export const metadata: Metadata = { title: "Data Import" };

export default function ImportPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Ingest"
        title="Data Import"
        description="Load the scenario, then append unseen event CSVs. Validation, deduplication, conflict quarantine and full deterministic replay — without restarting."
      />
      <SimulationStatus />
      <DataImport />
      <DatasetPanel />
    </div>
  );
}
