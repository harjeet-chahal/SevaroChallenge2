import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { recommendationActedOn } from "@/components/coordinator/alert-queue";
import { InterventionProgressBadge } from "@/components/workflow/status";
import type { Alert, Intervention } from "@/lib/api/types";

afterEach(cleanup);

const alert = { recommended_action_type: "escalate" } as Alert;
const intervention = (status: Intervention["status"], is_terminal: boolean) => ({
  id: "INT-TEST", title: "Clinical escalation", type: "escalation", status, is_terminal,
} as Intervention);

describe("linked alert intervention progress", () => {
  it("suppresses a recommendation while its intervention is open or completed", () => {
    expect(recommendationActedOn(alert, [intervention("pending_approval", false)])).toBe(true);
    expect(recommendationActedOn(alert, [intervention("completed", true)])).toBe(true);
  });
  it("allows retry after rejection and keeps other intervention types independent", () => {
    expect(recommendationActedOn(alert, [intervention("rejected", true)])).toBe(false);
    expect(recommendationActedOn(alert, [{ ...intervention("pending_approval", false), type: "split_shift" }])).toBe(false);
  });
  it("shows the action and progress together instead of repeating a recommendation", () => {
    render(<InterventionProgressBadge intervention={intervention("pending_approval", false)} />);
    expect(screen.getByText("Clinical escalation · Pending approval")).toBeTruthy();
  });
});
