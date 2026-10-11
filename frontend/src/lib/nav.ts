/**
 * The rescue loop as navigation: detect and propose on the coordinator page, approve as the
 * clinical lead, accept as the physician. Items with a ``section`` are anchors on the
 * coordinator page and light up as that section scrolls into view.
 */
export interface NavItem {
  id: "command" | "interventions" | "approvals" | "offers" | "network";
  label: string;
  /** Bottom-nav label on phones. */
  short: string;
  href: string;
  /** Loop step(s) this view covers, shown in mono beside the label. */
  step?: string;
  section?: string;
}

export const LOOP_NAV: readonly NavItem[] = [
  { id: "command", label: "Command center", short: "Command", href: "/coordinator", step: "01·02" },
  {
    id: "interventions",
    label: "Interventions",
    short: "Actions",
    href: "/coordinator#intervention-board",
    step: "03",
    section: "intervention-board",
  },
  { id: "approvals", label: "Clinical approval", short: "Approve", href: "/clinical-lead", step: "04" },
  { id: "offers", label: "Shift offers", short: "Offers", href: "/physician", step: "05" },
];

export const NETWORK_NAV: NavItem = {
  id: "network",
  label: "Network detail",
  short: "Network",
  href: "/coordinator#network-detail",
  section: "network-detail",
};

/** Coordinator sections in page order, for the scroll spy. */
export const COORDINATOR_SECTIONS = ["intervention-board", "network-detail"] as const;
