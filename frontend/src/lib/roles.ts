import { ClipboardList, ShieldCheck, Smartphone, type LucideIcon } from "lucide-react";

import type { DemoUserRole } from "@/lib/api/types";

export interface DemoRole {
  id: DemoUserRole;
  label: string;
  shortLabel: string;
  /** Role pill label on wide screens. */
  tabLabel: string;
  href: "/coordinator" | "/clinical-lead" | "/physician";
  description: string;
  icon: LucideIcon;
}

export const DEMO_ROLES: readonly DemoRole[] = [
  {
    id: "coordinator",
    label: "Operations Coordinator",
    shortLabel: "Coordinator",
    tabLabel: "Operations coordinator",
    href: "/coordinator",
    description:
      "Network-wide alerts, consult queues, physician activity and coverage forecasts. Proposes interventions.",
    icon: ClipboardList,
  },
  {
    id: "clinical_lead",
    label: "Clinical Lead",
    shortLabel: "Clinical lead",
    tabLabel: "Clinical lead",
    href: "/clinical-lead",
    description:
      "Reviews proposed interventions and their justification. Approves or rejects offers and escalations.",
    icon: ShieldCheck,
  },
  {
    id: "physician",
    label: "Off-Shift Physician",
    shortLabel: "Physician",
    tabLabel: "Off-shift physician",
    href: "/physician",
    description: "Sees only approved shift offers and accepts or declines them from a phone.",
    icon: Smartphone,
  },
];

export function roleForPath(pathname: string): DemoRole | undefined {
  return DEMO_ROLES.find(
    (role) => pathname === role.href || pathname.startsWith(`${role.href}/`),
  );
}
