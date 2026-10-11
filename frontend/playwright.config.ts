import { defineConfig } from "@playwright/test";

const apiPort = Number(process.env.E2E_API_PORT || 8000);
const frontendPort = Number(process.env.E2E_FRONTEND_PORT || 3000);
if (![apiPort, frontendPort].every((p) => Number.isInteger(p) && p >= 1024 && p <= 65535)) {
  throw new Error("E2E ports must be integers between 1024 and 65535.");
}
const apiUrl = `http://localhost:${apiPort}`;
process.env.E2E_API_URL = apiUrl;

/**
 * End-to-end tests drive the real UI against the real backend. Both servers are started
 * here (or reused if already running). The frontend talks to the API at
 * NEXT_PUBLIC_API_BASE_URL (default http://localhost:8000), baked in at build time.
 * Override E2E_API_PORT and E2E_FRONTEND_PORT to avoid an existing development server.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: { baseURL: `http://localhost:${frontendPort}`, viewport: { width: 1440, height: 1000 } },
  webServer: [
    {
      command:
        `cd ../backend && rm -f data/e2e.db data/e2e.db-wal data/e2e.db-shm && CORS_ORIGINS=http://localhost:${frontendPort},http://127.0.0.1:${frontendPort} DATABASE_URL=sqlite:///./data/e2e.db .venv/bin/uvicorn app.main:app --port ${apiPort}`,
      url: `${apiUrl}/api/health`,
      // Always a fresh database: offer history (weekly limits) must not leak between runs.
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `NEXT_PUBLIC_API_BASE_URL=${apiUrl} npm run build && npx next start -p ${frontendPort}`,
      url: `http://localhost:${frontendPort}`,
      reuseExistingServer: false,
      timeout: 240_000,
    },
  ],
});
