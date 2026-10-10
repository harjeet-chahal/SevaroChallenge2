"use client";

import { ShieldCheck } from "lucide-react";

import { Bullets } from "@/components/optimization/shared";
import { TrapSummary } from "@/components/optimization/staffing-view";
import { useKeyedResource } from "@/hooks/use-keyed-resource";
import { workflowApi } from "@/lib/api/endpoints";
import type { DemoUserRole } from "@/lib/api/types";

import { Block, ImpactTable } from "./intervention-detail";

/** Before/after coverage for one intervention, and live trap protection once active. */
export function ImpactView({
  role,
  versionKey,
  interventionId,
  tz,
}: {
  role: DemoUserRole;
  versionKey: string | null;
  interventionId: string;
  tz?: string | null;
}) {
  const key = versionKey ? `${versionKey}|impact|${interventionId}` : null;
  const impact = useKeyedResource(key, (signal) =>
    workflowApi.impact(interventionId, role, signal),
  );
  const data = impact.data;
  if (impact.error) return <p className="text-xs text-critical">{impact.error}</p>;
  if (!data) return <p className="text-xs text-muted-foreground">Loading impact…</p>;
  const routing = data.routing;
  return (
    <div className="space-y-3">
      {data.at_activation ? (
        <Block title="Coverage at activation (recalculated)">
          <ImpactTable impact={data.at_activation} tz={tz} />
        </Block>
      ) : null}
      {data.current ? (
        <Block title="Coverage now">
          <ImpactTable impact={data.current} tz={tz} />
        </Block>
      ) : null}
      {routing ? (
        <Block title="Split-shift trap protection (live)" icon={ShieldCheck}>
          <dl className="grid gap-2 rounded-lg border p-3 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">Intended hospitals (the need)</dt>
              <dd>{routing.intended_hospital_ids.join(", ")}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Authorized routing scope</dt>
              <dd className="font-semibold">{routing.authorized_scope_hospital_ids.join(", ")}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Credentialed at</dt>
              <dd>{routing.credentialed_hospital_ids.join(", ")}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Workload before joining</dt>
              <dd>
                {routing.workload_before_joining.actual_consults} consults (routing count seeded
                to {routing.workload_before_joining.seeded_routing_count})
              </dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Consults this shift now</dt>
              <dd>{routing.consults_this_shift_now}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Current routing proposals to them</dt>
              <dd>
                {routing.current_dispatch_proposals_to_physician.length
                  ? routing.current_dispatch_proposals_to_physician.join(", ")
                  : "none right now"}
              </dd>
            </div>
          </dl>
          <p className="text-xs text-muted-foreground">
            Baseline: {routing.baseline} {routing.disclaimer}
          </p>
        </Block>
      ) : null}
      {data.trap ? <TrapSummary trap={data.trap} /> : null}
      <Bullets items={data.notes} className="text-xs" />
    </div>
  );
}
