import { defineConfig } from "@playwright/test";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const python = path.join(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:8021",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" -m voiceledger.cli launch --port 8021 --no-open-browser`,
    cwd: root,
    url: "http://127.0.0.1:8021/api/v1/session",
    timeout: 120000,
    reuseExistingServer: false,
    env: {
      VOICELEDGER_DATA_DIR: path.join(
        root,
        ".cache",
        `browser-tests-${Date.now()}`,
      ),
    },
  },
});
