import type { Metadata } from "next";

import { DataImport } from "@/components/neurogrid/chaos";
import { DatasetPanel } from "@/components/dataset/dataset-panel";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Data Import" };

export default function ImportPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Import"
        description="Load the scenario, then append unseen event CSVs. Validation, deduplication, conflict quarantine and full deterministic replay — without restarting."
      />
      <DataImport />
      <DatasetPanel />
    </div>
  );
}
