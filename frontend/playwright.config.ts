import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests drive the real UI against the real backend. Both servers are started
 * here (or reused if already running). The frontend talks to the API at
 * NEXT_PUBLIC_API_BASE_URL (default http://localhost:8000), baked in at build time.
 * Stop any backend already on port 8000 first: the e2e backend always starts on a fresh DB.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3000", viewport: { width: 1440, height: 1000 } },
  webServer: [
    {
      command:
        "cd ../backend && rm -f data/e2e.db data/e2e.db-wal data/e2e.db-shm && DATABASE_URL=sqlite:///./data/e2e.db .venv/bin/uvicorn app.main:app --port 8000",
      url: "http://localhost:8000/api/health",
      // Always a fresh database: offer history (weekly limits) must not leak between runs.
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run build && npx next start -p 3000",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 240_000,
    },
  ],
});
