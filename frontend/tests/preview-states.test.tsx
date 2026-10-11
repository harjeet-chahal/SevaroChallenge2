import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DeadlineCard } from "@/components/neurogrid/command";
import { OptionCard, previewNote } from "@/components/neurogrid/simulator";
import type { LastSafeMoment, RescueOption, RescueTiming } from "@/lib/api/neurogrid";

afterEach(cleanup);

const timing = (sendable_now: boolean): RescueTiming => ({
  physician_id: "PHY-009",
  display_name: "Dr. Grace Okafor",
  lead: {
    approval_minutes: 5,
    response_minutes_expected: 4,
    response_minutes_conservative: 10,
    online_minutes: 15,
    expected_total_minutes: 24,
    conservative_total_minutes: 30,
    online_time_assumed: false,
  },
  earliest_valid_start: "2026-03-17T23:30:00Z",
  activation_expected_at: "2026-03-17T22:54:00Z",
  latest_initiation_expected: "2026-03-17T23:36:00Z",
  latest_initiation_conservative: "2026-03-17T23:30:00Z",
  covers_shortfall_start: true,
  eligible_at_start: true,
  sendable_now,
  eligibility_crossing: null,
  blocking: [],
});

const deadline = (sendable_now: boolean, opens: string | null): LastSafeMoment => ({
  shortfall_id: "LSM:SYN-008",
  hospital_id: "SYN-008",
  hospital_name: "Northfield Medical",
  timezone: "America/New_York",
  shortfall_at: "2026-03-18T00:00:00Z",
  shortfall_ends_at: null,
  minutes_until_shortfall: 100,
  deficit_physician_minutes: 120,
  worst_deficit: 1,
  phase: "green",
  latest_initiation_at: "2026-03-17T23:30:00Z",
  remaining_minutes: 70,
  best_physician_id: "PHY-009",
  action_window_minutes: 90,
  action_window_opens_at: opens,
  candidates: [timing(sendable_now)],
  mitigation: [],
  uncertainty: [],
  explanation: "",
});

describe("DeadlineCard: future planning vs action allowed now", () => {
  it("shows a planning preview, never 'if started now', outside the action window", () => {
    render(<DeadlineCard item={deadline(false, "2026-03-17T22:30:00Z")} compact />);
    expect(screen.getAllByText("Planning preview").length).toBeGreaterThan(0);
    expect(screen.queryByText(/if started now/)).toBeNull();
    expect(screen.getByText(/becomes permitted at 18:30 EDT/)).toBeTruthy();
    expect(screen.getByText(/90-minute action window/)).toBeTruthy();
    expect(screen.getByText(/View rescue preview/)).toBeTruthy();
  });

  it("keeps 'if started now' only when the backend says the offer is sendable now", () => {
    render(<DeadlineCard item={deadline(true, null)} compact />);
    expect(screen.queryByText("Planning preview")).toBeNull();
    expect(screen.getByText(/if started now/)).toBeTruthy();
    expect(screen.getByText(/Open rescue proposal/)).toBeTruthy();
  });
});

const option = (over: Partial<RescueOption>): RescueOption => ({
  option_id: "split:PHY-009",
  kind: "split_shift",
  label: "Split shift: Dr. Grace Okafor",
  feasible: true,
  simulation_only: false,
  requires_approval: true,
  physician_ids: ["PHY-009"],
  hospital_ids: ["SYN-008"],
  start_at: null,
  end_at: null,
  blocking_reasons: [],
  outcome: null,
  workload: null,
  lexicographic_key: [],
  rank: 1,
  recommended: false,
  why: [],
  uncertainty: [],
  proposal: { type: "split_shift" },
  planning_preview: false,
  actionable_from: null,
  ...over,
});

const noop = () => undefined;

describe("Simulator: future preview vs permanently comparison-only", () => {
  it("says 'Not available to propose yet' for a future rescue preview", () => {
    const o = option({
      feasible: false,
      simulation_only: true,
      planning_preview: true,
      actionable_from: "2026-03-17T22:30:00Z",
      proposal: null,
      blocking_reasons: ["Planning preview only: outside the 90-minute shortage look-ahead."],
    });
    expect(previewNote(o)).toMatch(/^Not available to propose yet: .*18:30 EDT/);
    render(<OptionCard o={o} onPropose={noop} busy={false} />);
    expect(screen.getAllByText(/Not available to propose yet/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/never/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Create rescue contract/ })).toBeNull();
  });

  it("keeps 'Comparison only — cannot be proposed' for permanently unsupported actions", () => {
    const o = option({
      kind: "shift_extension",
      feasible: false,
      simulation_only: true,
      proposal: null,
      blocking_reasons: ["Simulation only: no shift-extension authority."],
    });
    expect(previewNote(o)).toBe("Comparison only — cannot be proposed.");
    render(<OptionCard o={o} onPropose={noop} busy={false} />);
    expect(screen.getByText("Comparison only — cannot be proposed.")).toBeTruthy();
    expect(screen.queryByText(/Not available to propose yet/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Create rescue contract/ })).toBeNull();
  });

  it("offers the proposal button only when the backend allows proposing", () => {
    render(<OptionCard o={option({})} onPropose={noop} busy={false} />);
    expect(screen.getByRole("button", { name: /Create rescue contract/ })).toBeTruthy();
    cleanup();
    render(<OptionCard o={option({ proposal: null })} onPropose={noop} busy={false} />);
    expect(screen.queryByRole("button", { name: /Create rescue contract/ })).toBeNull();
  });
});
