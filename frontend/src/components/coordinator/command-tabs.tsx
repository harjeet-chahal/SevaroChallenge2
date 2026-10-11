"use client";

import { Database } from "lucide-react";
import Link from "next/link";
import { Tabs as TabsPrimitive } from "radix-ui";

import { AlertDetails } from "@/components/coordinator/alert-details";
import { AlertQueue } from "@/components/coordinator/alert-queue";
import { ConsultationQueue } from "@/components/coordinator/consultation-queue";
import { EventHistory } from "@/components/coordinator/event-history";
import { HospitalCoverage } from "@/components/coordinator/hospital-coverage";
import { PhysicianActivityPanel } from "@/components/coordinator/physician-activity";
import { DatasetPanel } from "@/components/dataset/dataset-panel";
import { RecommendationPanel } from "@/components/optimization/recommendation-panel";
import { useAnalysis } from "@/components/state/analysis-provider";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { useSystemStatus } from "@/components/status/system-status-provider";
import { InterventionBoard } from "@/components/workflow/intervention-board";
import { InterventionComposer } from "@/components/workflow/intervention-composer";
import { useWorkflow } from "@/components/workflow/workflow-provider";
import { useLiveResource } from "@/hooks/use-live-resource";
import { datasetApi } from "@/lib/api/endpoints";
import { datasetName } from "@/lib/labels";
import { cn } from "@/lib/utils";

/** Secondary detail views of the Command Center, one at a time under a pill tab row. */
export function CommandTabs() {
  const { alerts } = useAnalysis();
  const { data } = useOperationalState();
  const { interventions } = useWorkflow();
  const tabs = [
    { id: "alerts", label: "Alert queue", n: alerts.data?.total },
    { id: "coverage", label: "Hospital coverage", n: undefined },
    { id: "consults", label: "Consults & physicians", n: data?.summary.consults_open },
    { id: "interventions", label: "Interventions", n: interventions.data?.items.length },
    { id: "recommendations", label: "Recommendations", n: undefined },
    { id: "events", label: "Event history", n: undefined },
  ];
  return (
    <TabsPrimitive.Root defaultValue="alerts" className="flex flex-col gap-4">
      <TabsPrimitive.List
        aria-label="Detail views"
        className="flex gap-0.5 overflow-x-auto rounded-[14px] border bg-card-subtle px-2.5 py-2"
      >
        {tabs.map((t) => (
          <TabsPrimitive.Trigger
            key={t.id}
            value={t.id}
            className={cn(
              "flex items-center gap-2 rounded-lg px-3 py-2 text-[13.5px] font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
              "data-[state=active]:bg-selected data-[state=active]:text-foreground",
            )}
          >
            {t.label}
            {t.n !== undefined ? <span className="font-mono text-[11px] text-muted-foreground">{t.n}</span> : null}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      <TabsPrimitive.Content value="alerts" className="grid grid-cols-1 gap-4 min-[900px]:grid-cols-3">
        <AlertQueue className="min-[900px]:col-span-2" />
        <AlertDetails />
      </TabsPrimitive.Content>
      <TabsPrimitive.Content value="coverage">
        <HospitalCoverage />
      </TabsPrimitive.Content>
      <TabsPrimitive.Content value="consults" className="grid grid-cols-1 gap-4 min-[900px]:grid-cols-3">
        <ConsultationQueue className="min-[900px]:col-span-2" />
        <PhysicianActivityPanel />
      </TabsPrimitive.Content>
      <TabsPrimitive.Content value="interventions" className="flex flex-col gap-4">
        <InterventionComposer />
        <InterventionBoard />
      </TabsPrimitive.Content>
      <TabsPrimitive.Content value="recommendations">
        <RecommendationPanel />
      </TabsPrimitive.Content>
      <TabsPrimitive.Content value="events">
        <EventHistory />
      </TabsPrimitive.Content>
    </TabsPrimitive.Root>
  );
}

/** Header button naming the loaded dataset; links to Data Import. */
export function DatasetButton() {
  const { config } = useSystemStatus();
  const status = useLiveResource((s) => datasetApi.status(s));
  const active = status.data?.active;
  return (
    <Link
      href="/import"
      className="inline-flex items-center gap-2 rounded-lg border border-border-strong bg-card px-3 py-2 text-[13px] text-foreground-2 transition-colors hover:border-primary-border"
    >
      <Database className="size-4 text-muted-foreground" aria-hidden />
      {config?.dataset_loaded
        ? `Dataset · ${active ? datasetName(active) : "loaded"} · data v${config.data_version}`
        : "No dataset loaded · import"}
    </Link>
  );
}

/** The full dataset loader appears on the Command Center only while nothing is loaded. */
export function DatasetLoaderWhenEmpty() {
  const { config } = useSystemStatus();
  if (!config || config.dataset_loaded) return null;
  return <DatasetPanel />;
}
