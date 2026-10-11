import type { Metadata } from "next";

import { NetworkIntelligence } from "@/components/neurogrid/network";
import { PageHeader } from "@/components/shared/page-header";

export const metadata: Metadata = { title: "Network Intelligence" };

export default function NetworkPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Network Intelligence"
        description="Where the network is fragile, why shortfalls happen, and which backups are scarce. Removals and scenarios run on isolated copies."
      />
      <NetworkIntelligence />
    </div>
  );
}
