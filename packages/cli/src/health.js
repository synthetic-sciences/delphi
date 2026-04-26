import { setTimeout as sleep } from "node:timers/promises";
import { log } from "./log.js";

const API_BASE = process.env.SYNSCI_DELPHI_API_URL || "http://localhost:8742";

/** Poll /health until it returns 200, or time out. */
export async function waitForHealth({ timeoutMs = 240_000, intervalMs = 2_000 } = {}) {
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
  throw new Error(`API never reported healthy (${lastErr})`);
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
