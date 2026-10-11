import { readFileSync, existsSync, readdirSync } from "node:fs";
import path from "node:path";

import type { APIRequestContext } from "@playwright/test";

export const API = "http://localhost:8000";
const ROOT = path.resolve(__dirname, "..", "..");
const OFFICIAL = path.join(ROOT, "data");
const SAMPLE = path.join(ROOT, "backend", "sample_data", "synthetic_workflow");
export const COORD = { "X-Demo-Role": "coordinator", "X-Demo-Actor-Id": "e2e-coordinator" };

/** Load the official scenario (or the bundled workflow sample if absent): a fresh import. */
export async function loadScenario(request?: APIRequestContext): Promise<"official" | "sample"> {
  const dir = existsSync(path.join(OFFICIAL, "event_stream.csv")) ? OFFICIAL : SAMPLE;
  const files = readdirSync(dir).filter((f) => f.endsWith(".csv") || f.endsWith(".json"));
  const form = new FormData();
  for (const f of files) {
    form.append("files", new Blob([readFileSync(path.join(dir, f))]), f);
  }
  void request; // kept for call-site symmetry with Playwright fixtures
  const res = await fetch(`${API}/api/datasets/import`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`import failed: ${res.status} ${await res.text()}`);
  return dir === OFFICIAL ? "official" : "sample";
}

export async function api<T>(p: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${p}`, init);
  if (!res.ok) throw new Error(`${p}: ${res.status} ${await res.text()}`);
  return (await res.json()) as T;
}
