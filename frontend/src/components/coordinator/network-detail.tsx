"use client";

import { History, Hospital, Inbox, Sparkles, Users } from "lucide-react";

import { RecommendationPanel } from "@/components/optimization/recommendation-panel";
import { PILL_TONES } from "@/components/shared/pill";
import { BareSections } from "@/components/shared/section-card";
import { useAnalysis } from "@/components/state/analysis-provider";
import { useOperationalState } from "@/components/state/operational-state-provider";
import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

import { ConsultationQueue } from "./consultation-queue";
import { EventHistory } from "./event-history";
import { HospitalCoverage } from "./hospital-coverage";
import { PhysicianActivityPanel } from "./physician-activity";
import { SECTION_IDS } from "./section-ids";
import { type DetailTab, useCoordinatorView } from "./view-provider";

/** Tab badges flag what needs attention, in words — never a bare inventory count. */
function Flag({ children, tone }: { children: React.ReactNode; tone: "warning" | "critical" }) {
  return (
    <span
      className={cn(
        "rounded-full border px-1.5 text-micro leading-4 font-semibold whitespace-nowrap",
        tone === "critical" ? PILL_TONES.critical : PILL_TONES.warning,
      )}
    >
      {children}
    </span>
  );
}

/**
 * The supporting views — forecast, queues, people, optimizer and raw log — one at a time
 * instead of stacked, so the page reads as overview first, detail on demand.
 */
export function NetworkDetail({ className }: { className?: string }) {
  const { detailTab, setDetailTab } = useCoordinatorView();
  const { metrics } = useAnalysis();
  const { data } = useOperationalState();
  const coverage = metrics.data?.coverage;
  const gapNow = coverage ? Number(coverage.gap_now ?? 0) : 0;
  const gaps = coverage ? gapNow + Number(coverage.gap_projected ?? 0) : 0;
  const unassigned = data?.summary.consults_open_unassigned ?? 0;
  const flagged =
    data?.physicians.filter(
      (p) => p.on_shift !== false && p.flags.some((f) => f.severity !== "info"),
    ).length ?? 0;

  const tabs: {
    value: DetailTab;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    flag?: React.ReactNode;
  }[] = [
    {
      value: "coverage",
      label: "Coverage forecast",
      icon: Hospital,
      flag: gaps ? (
        <Flag tone={gapNow ? "critical" : "warning"}>
          {gaps} gap{gaps === 1 ? "" : "s"}
        </Flag>
      ) : null,
    },
    {
      value: "consults",
      label: "Consults",
      icon: Inbox,
      flag: unassigned ? <Flag tone="warning">{unassigned} unassigned</Flag> : null,
    },
    {
      value: "physicians",
      label: "Physicians",
      icon: Users,
      flag: flagged ? <Flag tone="warning">{flagged} flagged</Flag> : null,
    },
    { value: "optimizer", label: "Optimizer", icon: Sparkles },
    { value: "events", label: "Event log", icon: History },
  ];

  return (
    <section
      id={SECTION_IDS.detail}
      aria-label="Network detail"
      className={cn("scroll-mt-24", className)}
    >
      <Card className="w-full min-w-0 gap-0 py-0">
        <Tabs
          value={detailTab}
          onValueChange={(v) => setDetailTab(v as DetailTab)}
          className="gap-0"
        >
          <div className="overflow-x-auto border-b border-border-subtle px-2.5 pt-2">
            <TabsList variant="line" className="h-10 w-max">
              {tabs.map((t) => (
                <TabsTrigger key={t.value} value={t.value} className="px-3">
                  <t.icon aria-hidden />
                  {t.label}
                  {t.flag}
                </TabsTrigger>
              ))}
            </TabsList>
          </div>
          <BareSections>
            <TabsContent value="coverage" className="p-4">
              <HospitalCoverage />
            </TabsContent>
            <TabsContent value="consults" className="p-4">
              <ConsultationQueue />
            </TabsContent>
            <TabsContent value="physicians" className="p-4">
              <PhysicianActivityPanel />
            </TabsContent>
            <TabsContent value="optimizer" className="p-4">
              <RecommendationPanel />
            </TabsContent>
            <TabsContent value="events" className="p-4">
              <EventHistory />
            </TabsContent>
          </BareSections>
        </Tabs>
      </Card>
    </section>
  );
}
