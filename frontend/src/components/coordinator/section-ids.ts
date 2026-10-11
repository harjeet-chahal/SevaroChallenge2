/**
 * Section anchors on the coordinator page, in reading order. A plain module (not a client
 * one) so the server-rendered page can read the values too.
 */
export const SECTION_IDS = {
  triage: "triage",
  interventions: "intervention-board",
  detail: "network-detail",
} as const;
