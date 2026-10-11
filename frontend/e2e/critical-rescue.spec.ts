import { expect, test } from "@playwright/test";

import { api, loadScenario } from "./helpers";

interface Option { recommended: boolean; kind: string; physician_ids: string[]; hospital_ids: string[] }

test("detect → simulate → propose → approve → offer → accept → activate → verify", async ({ page, request }) => {
  const scenario = await loadScenario(request);
  if (scenario === "official") {
    // Future rescue impact stays visible before main's action window opens.
    const preview = await api<{ options: { kind: string; simulation_only: boolean; proposal: unknown; outcome: unknown }[] }>(
      "/api/intelligence/simulate?hospital_id=SYN-008",
    );
    expect(preview.options.some((o) => o.kind === "split_shift" && o.simulation_only && o.outcome && !o.proposal)).toBe(true);
    await api("/api/simulation/advance", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ minutes: 11 }),
    });
  }
  const sim = await api<{ options: Option[]; target_hospital_ids: string[] }>("/api/intelligence/simulate");
  const best = sim.options.find((o) => o.recommended)!;
  expect(best.kind).toBe("split_shift");
  const physician = best.physician_ids[0];

  // Command center shows the ranked problem and a last-safe-moment deadline.
  await page.goto("/coordinator");
  await expect(page.getByLabel("Priority one")).toBeVisible();
  await expect(page.getByText("Last safe moment ·").first()).toBeVisible();

  // Rescue simulator: create the recommended contract.
  await page.goto(`/simulator?hospital=${sim.target_hospital_ids[0]}`);
  await expect(page.getByText("Recommended", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Create rescue contract" }).first().click();
  await expect(page.getByText(/created — pending approval/)).toBeVisible();

  // Clinical lead approves (re-validated server-side) and sends the simulated offer.
  await page.goto("/clinical-lead");
  await expect(page.getByLabel("Decision freshness")).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Send approved offer (simulated)" }).click();
  await expect(page.getByText(/Sent|offer_sent|offer sent/i).first()).toBeVisible();

  // The physician accepts on the phone view (no patient information shown).
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/physician");
  await page.locator("#simulated-physician").selectOption(physician);
  await expect(page.getByText("Split-shift offer").first()).toBeVisible();
  await expect(page.getByText(/CON-\d+/)).toHaveCount(0);
  await page.getByRole("button", { name: "Accept" }).first().click();
  await expect(page.getByText(/accepted|confirmed/i).first()).toBeVisible();

  // Not online yet: no recovery may be claimed.
  const pending = await api<{ verdict: string }>(
    `/api/rescue-contracts/${(await api<{ items: { id: string }[] }>("/api/interventions", { headers: { "X-Demo-Role": "coordinator" } })).items[0].id}/verification`,
    { headers: { "X-Demo-Role": "coordinator" } },
  );
  expect(pending.verdict).toBe("pending");

  // Advance the simulation clock past activation, then verify the recovery.
  await api("/api/simulation/advance", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ minutes: 60 }),
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/contracts");
  await page.getByRole("button", { name: "Verify & record" }).click();
  await expect(page.getByText(/Recorded in the audit log: (resolved|partially resolved)/)).toBeVisible();
});
