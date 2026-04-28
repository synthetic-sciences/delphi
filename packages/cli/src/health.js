import { setTimeout as sleep } from "node:timers/promises";
import { log } from "./log.js";
import { run } from "./system.js";
import { SOURCE_DIR } from "./paths.js";

const API_BASE = process.env.SYNSCI_DELPHI_API_URL || "http://localhost:8742";

// 10 minutes. The original 4-min budget worked fine on Linux but was
// genuinely tight on Mac Docker Desktop's first cold boot — the api's
// uvicorn factory mode imports torch + transformers + sentence-
// transformers, which on a 4 CPU / 8 GB Mac VM with rosetta emulation
// can stretch to 5-7 minutes. 10 min covers the slowest realistic
// case without forcing the user to wait forever on a genuinely stuck
// container (we dump api logs on timeout so the cause surfaces).
const DEFAULT_HEALTH_TIMEOUT_MS = 600_000;

/** Pull the last `n` lines from `docker compose logs api`. Best-effort —
 *  used only to enrich the error when the api never came up healthy. */
async function dumpApiLogs({ tail = 60 } = {}) {
  const { code, stdout, stderr } = await run(
    "docker", ["compose", "logs", "api", "--tail", String(tail), "--no-color"],
    { silent: true, cwd: SOURCE_DIR },
  );
  if (code !== 0) return null;
  // Drop the noise of repeated GET /health 200 lines so the actual
  // stack trace / startup error is at the bottom of what we surface.
  const filtered = (stdout || "")
    .split("\n")
    .filter((line) => !/GET \/health HTTP\/1\.1.* 200 OK/.test(line))
    .join("\n");
  return filtered || stderr || null;
}

/** Poll /health until it returns 200, or time out. On timeout, dump the
 *  api's recent logs into the error message so the user sees WHY the
 *  service didn't come up — not just "fetch failed". */
export async function waitForHealth({ timeoutMs = DEFAULT_HEALTH_TIMEOUT_MS, intervalMs = 2_000 } = {}) {
  const start = Date.now();
  let lastErr = null;
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3_000) });
      if (res.ok) return true;
      lastErr = `status ${res.status}`;
    } catch (e) {
      lastErr = e?.message || String(e);
    }
    await sleep(intervalMs);
  }

  // Timed out — try to surface what's actually wrong. compose logs may
  // fail (no install dir, docker offline) — degrade gracefully rather
  // than mask the original error.
  const apiLogs = await dumpApiLogs().catch(() => null);
  const elapsedSec = Math.round((Date.now() - start) / 1000);
  let msg = `API never reported healthy after ${elapsedSec}s (${lastErr})`;
  if (apiLogs) {
    msg += `\n\nLast api container output:\n${"─".repeat(60)}\n${apiLogs.trimEnd()}\n${"─".repeat(60)}`;
  }
  throw new Error(msg);
}

/** Call /api/bootstrap to mint an admin API key for the CLI. */
export async function bootstrap({ password, clientName = "cli-bootstrap" }) {
  const res = await fetch(`${API_BASE}/api/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password, client_name: clientName }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`bootstrap failed (${res.status}): ${body}`);
  }
  const data = await res.json();
  if (!data?.success || !data?.api_key) {
    throw new Error(`bootstrap returned unexpected payload: ${JSON.stringify(data)}`);
  }
  return data;
}

export { API_BASE };
