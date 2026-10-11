import { expect, test } from "@playwright/test";

import { api, loadScenario } from "./helpers";

test("chaos scenarios run on isolated branches and report genuine assertions", async ({ page, request }) => {
  await loadScenario(request);
  const pick = (c: { data_version: number; workflow_version: number; simulation_time: string }) => ({
    data_version: c.data_version,
    workflow_version: c.workflow_version,
    simulation_time: c.simulation_time,
  });
  const before = pick(await api("/api/config"));
  await page.goto("/chaos");
  for (const title of ["Hospital surge", "Missing desktop helper", "Late and duplicate events"]) {
    await page.getByRole("button", { name: `Run ${title}` }).click();
    await expect(page.getByText(title, { exact: true }).nth(1)).toBeVisible({ timeout: 60_000 });
  }
  await expect(page.getByText("PASS", { exact: true })).toHaveCount(3);
  await expect(page.getByText("baseline untouched", { exact: true })).toHaveCount(3);
  expect(pick(await api("/api/config"))).toEqual(before);
});
