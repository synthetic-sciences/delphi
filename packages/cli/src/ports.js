import { createServer } from "node:net";
import { run } from "./system.js";

/**
 * Probe a TCP port for availability.
 *
 * Returns true when the OS can hand us the port to listen on. The check
 * binds, releases, and returns the result — if anyone else holds it
 * (active server, lingering TIME_WAIT, ipv4/ipv6 collision, firewall
 * binding restriction) the listen call rejects and we report busy.
 *
 * Race window: a port free at probe time can be claimed by another
 * process before docker tries to bind it. Sub-second exposure;
 * acceptable for an install pre-flight.
 */
export function isPortFree(port, host = "0.0.0.0") {
  return new Promise((resolve) => {
    const srv = createServer();
    srv.unref();
    srv.once("error", () => resolve(false));
    srv.once("listening", () => srv.close(() => resolve(true)));
    try {
      srv.listen(port, host);
    } catch {
      resolve(false);
    }
  });
}

/**
 * Try to identify what's holding a port. Best-effort, used only to
 * enrich error messages — falls back to a generic note if `lsof` /
 * `ss` aren't available or don't list the port.
 *
 * Returns a short string like "Next.js dev server (PID 12345)" or
 * `null` when we can't tell.
 */
export async function whoHoldsPort(port) {
  // Try each tool; missing-binary ENOENT is silently treated as a miss
  // so we never block on `lsof` or `ss` not being installed (Arch +
  // some minimal containers ship without lsof; alpine without ss).
  const tryRun = async (cmd, args) => {
    try {
      return await run(cmd, args, { silent: true });
    } catch (e) {
      if (e?.code === "ENOENT") return { code: 127, stdout: "", stderr: "" };
      return { code: 1, stdout: "", stderr: e?.message || "" };
    }
  };

  // macOS + most Linux desktops have lsof.
  // Output: "node    12345 user   23u  IPv6 ..."
  const lsof = await tryRun("lsof", ["-iTCP:" + port, "-sTCP:LISTEN", "-Pn"]);
  if (lsof.code === 0 && lsof.stdout) {
    const lines = lsof.stdout.split("\n").filter((l) => l && !l.startsWith("COMMAND"));
    if (lines.length > 0) {
      const fields = lines[0].split(/\s+/);
      const cmd = fields[0];
      const pid = fields[1];
      if (cmd && pid) return `${cmd} (PID ${pid})`;
    }
  }
  // Linux fallback. ss ships with iproute2 on most distros.
  const ss = await tryRun("ss", ["-Hltnp", `( sport = :${port} )`]);
  if (ss.code === 0 && ss.stdout) {
    // Format: LISTEN 0 4096 *:3000 *:* users:(("node",pid=12345,fd=23))
    const m = ss.stdout.match(/users:\(\("([^"]+)",pid=(\d+)/);
    if (m) return `${m[1]} (PID ${m[2]})`;
  }
  return null;
}

/**
 * Walk upwards from `start`, return the first free port within
 * `[start, start + maxScan)`. Throws if none free.
 */
export async function findFreePort(start, { maxScan = 50, host = "0.0.0.0" } = {}) {
  for (let p = start; p < start + maxScan; p++) {
    if (await isPortFree(p, host)) return p;
  }
  throw new Error(
    `No free port in [${start}, ${start + maxScan}). ` +
    `Free up at least one port in that range and retry.`,
  );
}

/**
 * Resolve the host ports the install will bind, scanning upward from
 * the conventional defaults. Each result includes the original
 * default and the chosen port; the caller decides what to do when
 * `chosen !== requested` (typically: write to .env so docker-compose
 * picks it up via ${PORT:-default}).
 *
 * `host` is hardcoded to '0.0.0.0' to match docker-compose's bind —
 * a port can be free on 127.0.0.1 but busy on 0.0.0.0.
 */
export async function discoverPorts({
  frontend = 3000,
  api = 8742,
  postgres = 5432,
} = {}) {
  return {
    frontend: await pickPort("frontend", frontend),
    api: await pickPort("api", api),
    postgres: await pickPort("postgres", postgres),
  };
}

async function pickPort(name, requested) {
  if (await isPortFree(requested)) {
    return { name, requested, chosen: requested, holder: null };
  }
  const holder = await whoHoldsPort(requested);
  const chosen = await findFreePort(requested + 1).catch(() => null);
  return { name, requested, chosen, holder };
}
