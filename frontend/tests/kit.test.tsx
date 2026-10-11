import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  CLASS_LABEL,
  ClassBadge,
  ConfidenceBadge,
  ContractPhaseBadge,
  PHASE,
  fmtMin,
  fmtPm,
} from "@/components/neurogrid/kit";

afterEach(cleanup);

describe("formatting", () => {
  it("formats minutes without inventing precision", () => {
    expect(fmtMin(null)).toBe("—");
    expect(fmtMin(45)).toBe("45 min");
    expect(fmtMin(60)).toBe("1 h");
    expect(fmtMin(135)).toBe("2 h 15 min");
    expect(fmtMin(-12)).toBe("-12 min");
  });
  it("labels physician-minutes", () => {
    expect(fmtPm(120)).toBe("120 phys-min");
    expect(fmtPm(undefined)).toBe("—");
  });
});

describe("status never conveyed by colour alone", () => {
  it("renders every availability class as text", () => {
    for (const [cls, label] of Object.entries(CLASS_LABEL)) {
      render(<ClassBadge cls={cls as keyof typeof CLASS_LABEL} />);
      expect(screen.getByText(label)).toBeTruthy();
      cleanup();
    }
  });
  it("marks evidence labels as not calibrated probabilities", () => {
    render(<ConfidenceBadge c="STALE" />);
    expect(screen.getByText("stale").closest("[title]")?.getAttribute("title")).toMatch(/not a calibrated probability/);
  });
  it("renders contract phases readably", () => {
    render(<ContractPhaseBadge phase="REVALIDATION_REQUIRED" />);
    expect(screen.getByText("revalidation required")).toBeTruthy();
  });
  it("has a label for every last-safe-moment phase", () => {
    expect(Object.keys(PHASE).sort()).toEqual(["amber", "green", "missed", "no_candidate", "red"]);
  });
});
