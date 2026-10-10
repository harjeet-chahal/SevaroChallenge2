"use client";

import { FlaskConical, Route, Scale, Sparkles, UserPlus } from "lucide-react";

import { SectionCard } from "@/components/shared/section-card";
import { TagBadge } from "@/components/shared/status-badges";
import { StateFallback } from "@/components/state/state-fallback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { KeyedResource } from "@/hooks/use-keyed-resource";
import { cn } from "@/lib/utils";

import { ComparisonView } from "./comparison-view";
import { type RecommendationTab, useOptimization } from "./optimization-provider";
import { RoutingView } from "./routing-view";
import { StaffingView } from "./staffing-view";
import { WhatIfView } from "./whatif-view";

function Loaded<T>({
  resource,
  feature,
  children,
}: {
  resource: KeyedResource<T>;
  feature: string;
  children: (data: T) => React.ReactNode;
}) {
  if (!resource.data) {
    return (
      <StateFallback
        feature={feature}
        whenNoDataset="Load a dataset to see optimizer recommendations."
        resource={resource}
      />
    );
  }
  return (
    <div className={cn(resource.loading && "opacity-60 transition-opacity")}>
      {children(resource.data)}
    </div>
  );
}

/**
 * Optimizer recommendations (Phase 4). Everything shown is a proposal: routing is not
 * executed, offers are not sent, and projected coverage is never shown as confirmed.
 */
export function RecommendationPanel({ className }: { className?: string }) {
  const { dispatch, staffing, comparison, tab, setTab } = useOptimization();
  return (
    <SectionCard
      className={className}
      title="Recommendations"
      icon={Sparkles}
      description="Optimizer proposals for routing and split-shift staffing, with the reasoning behind each. Acting on one opens a validated proposal; nothing is executed from this panel."
      action={<TagBadge tone="info">Proposals only</TagBadge>}
    >
      <Tabs value={tab} onValueChange={(v) => setTab(v as RecommendationTab)}>
        <TabsList className="w-full overflow-x-auto sm:w-fit">
          <TabsTrigger value="routing">
            <Route aria-hidden className="max-sm:hidden" />
            Routing
          </TabsTrigger>
          <TabsTrigger value="staffing">
            <UserPlus aria-hidden className="max-sm:hidden" />
            Split shifts
          </TabsTrigger>
          <TabsTrigger value="comparison">
            <Scale aria-hidden className="max-sm:hidden" />
            Compare
          </TabsTrigger>
          <TabsTrigger value="whatif">
            <FlaskConical aria-hidden className="max-sm:hidden" />
            What-if
          </TabsTrigger>
        </TabsList>
        <TabsContent value="routing" className="pt-3">
          <Loaded resource={dispatch} feature="consult routing recommendations">
            {(data) => <RoutingView data={data} />}
          </Loaded>
        </TabsContent>
        <TabsContent value="staffing" className="pt-3">
          <Loaded resource={staffing} feature="split-shift recommendations">
            {(data) => <StaffingView data={data} />}
          </Loaded>
        </TabsContent>
        <TabsContent value="comparison" className="pt-3">
          <Loaded resource={comparison} feature="optimization comparison">
            {(data) => <ComparisonView data={data} />}
          </Loaded>
        </TabsContent>
        <TabsContent value="whatif" className="pt-3">
          <Loaded resource={staffing} feature="what-if preview">
            {(data) => <WhatIfView staffing={data} />}
          </Loaded>
        </TabsContent>
      </Tabs>
    </SectionCard>
  );
}
