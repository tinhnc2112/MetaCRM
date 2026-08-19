import { spawnSync } from "node:child_process";
import path from "node:path";

export default function globalTeardown() {
  const backendRoot = path.resolve(__dirname, "../../backend");
  const result = spawnSync("python", ["scripts/e2e_harness.py", "cleanup"], {
    cwd: backendRoot,
    env: { ...process.env, METACRM_E2E: "true", APP_ENV: "test" },
    encoding: "utf8"
  });

  if (result.status !== 0) {
    throw new Error(`E2E database cleanup failed: ${result.stderr || result.stdout}`);
  }
}
