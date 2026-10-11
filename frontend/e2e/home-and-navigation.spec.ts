import { expect, test } from "@playwright/test";

import { loadScenario } from "./helpers";

const status = (page: import("@playwright/test").Page) => page.getByText(/^Story · /);

test("home replay is labelled as an illustrative demo and its controls work", async ({ page, request }) => {
  await loadScenario(request);
  await page.goto("/");
  await expect(page.getByText("Illustrative demo — not live operational data")).toBeVisible();
  await expect(page.getByText(/live simulation clock stays at/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /human-approved rescue/ })).toBeVisible();
  await expect(page.getByText(/heal itself/)).toHaveCount(0);
  await expect(page.getByText(/routing eligibility failure/i)).toHaveCount(0);

  await expect(status(page)).toHaveText("Story · Rhythm stable");
  await page.getByRole("button", { name: /Illustrative network rhythm monitor/ }).click();
  await expect(status(page)).toHaveText("Story · ALARM · Northfield coverage");

  // Pause holds the stage; play resumes.
  await page.getByRole("button", { name: "Pause replay" }).click();
  await page.getByRole("button", { name: "Jump to Forecast" }).click();
  await page.waitForTimeout(3200);
  await expect(page.getByRole("button", { name: "Jump to Forecast" })).toHaveAttribute("aria-current", "step");
  await page.getByRole("button", { name: "Play replay" }).click();
  await expect(page.getByRole("button", { name: "Jump to Decide" })).toHaveAttribute("aria-current", "step", {
    timeout: 6000,
  });

  await page.getByRole("button", { name: "Jump to Verify" }).click();
  await expect(status(page)).toHaveText("Story · Recovered · verified");
});

test.describe("reduced motion", () => {
  test.use({ contextOptions: { reducedMotion: "reduce" } });

  test("the replay never auto-advances and moves only by click", async ({ page, request }) => {
    await loadScenario(request);
    await page.goto("/");
    await expect(page.getByRole("button", { name: /Pause replay|Play replay/ })).toHaveCount(0);
    await page.getByRole("button", { name: /Illustrative network rhythm monitor/ }).click();
    await expect(page.getByRole("button", { name: "Jump to Detect" })).toHaveAttribute("aria-current", "step");
    await page.waitForTimeout(3500);
    await expect(page.getByRole("button", { name: "Jump to Detect" })).toHaveAttribute("aria-current", "step");
    await page.getByRole("button", { name: "Jump to Simulate" }).click();
    await expect(page.getByRole("button", { name: "Jump to Simulate" })).toHaveAttribute("aria-current", "step");
  });
});

test("desktop sidebar and role tabs navigate", async ({ page, request }) => {
  await loadScenario(request);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/coordinator");
  const loop = page.getByRole("navigation", { name: "Rescue loop" }).first();
  for (const [label, path, title] of [
    ["Time machine", "/time-machine", "Coverage Time Machine"],
    ["Network", "/network", "Network Intelligence"],
    ["Rescue simulator", "/simulator", "Rescue Simulator"],
    ["Rescue contracts", "/contracts", "Rescue Contracts"],
  ] as const) {
    await loop.getByRole("link", { name: label }).click();
    await expect(page).toHaveURL(new RegExp(`${path}$|${path}\\?`));
    await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
  }
  await page.getByRole("navigation", { name: "Demo role" }).getByRole("link", { name: /Clinical lead/ }).click();
  await expect(page).toHaveURL(/\/clinical-lead$/);
  await expect(page.getByRole("button", { name: "Advance simulation 5 minutes" }).first()).toBeVisible();
});

test("phone bottom bar and role tabs navigate without horizontal scroll", async ({ page, request }) => {
  await loadScenario(request);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/", "/coordinator", "/simulator", "/contracts", "/physician"]) {
    await page.goto(path);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  }
  await page.goto("/coordinator");
  const bottom = page.getByRole("navigation", { name: "Rescue loop" }).last();
  await bottom.getByRole("link", { name: "Rescue simulator" }).click();
  await expect(page).toHaveURL(/\/simulator/);
  await bottom.getByRole("link", { name: "Time machine" }).click();
  await expect(page).toHaveURL(/\/time-machine$/);
  await page.getByRole("navigation", { name: "Demo role" }).getByRole("link", { name: /Lead/ }).click();
  await expect(page).toHaveURL(/\/clinical-lead$/);
  await page.getByRole("navigation", { name: "Demo role" }).getByRole("link", { name: /MD|Physician/ }).click();
  await expect(page).toHaveURL(/\/physician$/);
  await expect(page.locator("#simulated-physician")).toBeVisible();
});
