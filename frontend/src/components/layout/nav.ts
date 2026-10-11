/** The rescue loop as navigation: each page is a stage of DETECT → … → VERIFY. */
export interface NavItem {
  href: string;
  label: string;
  short: string;
  stage?: string;
  badge?: "critical-alerts" | "pending-approvals";
}

export const LOOP_NAV: readonly NavItem[] = [
  { href: "/coordinator", label: "Command center", short: "Command", stage: "01·02", badge: "critical-alerts" },
  { href: "/time-machine", label: "Time machine", short: "Forecast", stage: "03" },
  { href: "/network", label: "Network", short: "Network", stage: "04" },
  { href: "/simulator", label: "Rescue simulator", short: "Simulate", stage: "05" },
  { href: "/clinical-lead", label: "Clinical approval", short: "Approve", stage: "06", badge: "pending-approvals" },
  { href: "/contracts", label: "Rescue contracts", short: "Contracts", stage: "07·08" },
];

export const TOOL_NAV: readonly NavItem[] = [
  { href: "/chaos", label: "Chaos lab", short: "Chaos" },
  { href: "/import", label: "Data import", short: "Import" },
];

/** Pages that use the operations shell (sidebar on desktop, bottom bar on mobile). */
export function isOpsPath(pathname: string): boolean {
  return [...LOOP_NAV, ...TOOL_NAV].some((i) => isActive(pathname, i.href));
}

export function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
