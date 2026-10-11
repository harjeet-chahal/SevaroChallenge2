import { expect, test } from "@playwright/test";

import { api, COORD, loadScenario } from "./helpers";

test("alerts show linked intervention progress and block another open escalation", async ({ page, request }) => {
  await loadScenario(request);
  const { alerts } = await api<{ alerts: { alert_id: string; title: string }[] }>("/api/alerts");
  const alert = alerts[0];
  const intervention = await api<{ id: string }>("/api/interventions", {
    method: "POST",
    headers: { ...COORD, "content-type": "application/json" },
    body: JSON.stringify({ type: "escalation", alert_id: alert.alert_id }),
  });
  await page.goto("/coordinator");
  await page.getByRole("button").filter({ hasText: alert.title }).first().click();
  await expect(page.getByText("Already done about this problem", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: intervention.id, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Request escalation — unavailable/ })).toHaveAttribute("aria-disabled", "true");
  await expect(page.getByText(/Clinical escalation · Pending approval/).first()).toBeVisible();
});
