import { expect, test } from "@playwright/test";

import { api, COORD, loadScenario } from "./helpers";

test("the clinical lead sees a stale-decision warning after state changes under a proposal", async ({ page, request }) => {
  await loadScenario(request);
  const sim = await api<{ options: { recommended: boolean; proposal: Record<string, unknown> | null }[] }>(
    "/api/intelligence/simulate",
  );
  const proposal = sim.options.find((o) => o.recommended)!.proposal!;
  await api("/api/interventions", {
    method: "POST",
    headers: { ...COORD, "content-type": "application/json" },
    body: JSON.stringify(proposal),
  });
  await page.goto("/clinical-lead");
  await expect(page.getByText(/proposed on the current data version/)).toBeVisible();

  const cfg = await api<{ simulation_time: string }>("/api/config");
  await api("/api/events", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      event_id: "E2E-STALE-1",
      event_type: "camera_active",
      event_time: cfg.simulation_time,
      physician_id: (await api<{ physician_id: string; on_shift: boolean }[]>("/api/physicians")).find((p) => p.on_shift)!
        .physician_id,
    }),
  });
  await page.reload();
  await expect(page.getByText(/state has changed since proposal/)).toBeVisible();
});
