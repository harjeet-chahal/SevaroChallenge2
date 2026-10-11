import { expect, test } from "@playwright/test";

import { api, loadScenario } from "./helpers";

test("an unseen event CSV is validated, previewed and applied without restart", async ({ page, request }) => {
  await loadScenario(request);
  const before = await api<{ data_version: number; simulation_time: string }>("/api/config");
  const coverage = await api<{ hospitals: { hospital_id: string }[] }>("/api/coverage");
  const hospital = coverage.hospitals[0].hospital_id;
  const now = new Date(before.simulation_time).getTime();
  const iso = (ms: number) => new Date(ms).toISOString();
  const csv =
    "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description\n" +
    `E2E-1,${iso(now + 4 * 60_000)},${iso(now + 4 * 60_000 + 3000)},E2E-C1,consult_received,,${hospital},Stroke consult request received\n` +
    `E2E-1,${iso(now + 4 * 60_000)},${iso(now + 4 * 60_000 + 3000)},E2E-C1,consult_received,,${hospital},Stroke consult request received\n` +
    `E2E-2,${iso(now + 5 * 60_000)},${iso(now + 5 * 60_000 + 2000)},E2E-C1,consult_triaged,,${hospital},Triaged\n`;

  await page.goto("/import");
  await page.getByLabel("Event CSV file").setInputFiles({ name: "judges.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Validate & preview impact" }).click();
  await expect(page.getByText("valid", { exact: true })).toBeVisible();
  await expect(page.getByText("2 new")).toBeVisible();
  await expect(page.getByText("1 duplicates")).toBeVisible();
  // Preview changed nothing.
  expect((await api<{ data_version: number }>("/api/config")).data_version).toBe(before.data_version);

  await page.getByRole("button", { name: "Apply events" }).click();
  await expect(page.getByText(/Applied: 2 new, 1 duplicates/)).toBeVisible();
  const after = await api<{ data_version: number; simulation_time: string }>("/api/config");
  expect(after.data_version).toBe(before.data_version + 1);
  expect(new Date(after.simulation_time).getTime()).toBeGreaterThan(now);
  const consult = await api<{ stage: string }>("/api/consultations/E2E-C1");
  expect(consult.stage).toBe("triaged");
});

test("a malformed CSV is rejected with row errors and stores nothing", async ({ page, request }) => {
  await loadScenario(request);
  const before = await api<{ data_version: number }>("/api/config");
  const bad = "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description\nBAD-1,not-a-time,,,consult_received,,,x\n";
  await page.goto("/import");
  await page.getByLabel("Event CSV file").setInputFiles({ name: "bad.csv", mimeType: "text/csv", buffer: Buffer.from(bad) });
  await page.getByRole("button", { name: "Validate & preview impact" }).click();
  await expect(page.getByText("invalid", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Apply events" })).toBeDisabled();
  expect((await api<{ data_version: number }>("/api/config")).data_version).toBe(before.data_version);
});
