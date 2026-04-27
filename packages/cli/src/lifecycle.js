import fs from "node:fs/promises";
import readline from "node:readline";
import pc from "picocolors";
import { spawn } from "node:child_process";
import { log, banner, spinner } from "./log.js";
import { composePull, composeBuild, composeUp, composeDown, composeStatus, composeLogs } from "./docker.js";
import { loadState } from "./env.js";
import { ENV_FILE } from "./paths.js";
import { waitForHealth, API_BASE } from "./health.js";

const DASHBOARD_URL = "http://localhost:3000";

async function readSystemPassword() {
  const text = await fs.readFile(ENV_FILE, "utf-8");
  const match = text.match(/^SYSTEM_PASSWORD=(.+)$/m);
  if (!match) {
    throw new Error(
      "SYSTEM_PASSWORD not found in .env — your install looks corrupted, try `npx @synsci/delphi init --force`.",
    );
  }
  return match[1].trim();
}

/** Trade SYSTEM_PASSWORD for a single-use magic id; the resulting URL,
 *  when hit by the browser, sets a session cookie and redirects to
 *  /overview — no password ever appears in URL bar / history / scrollback. */
async function mintMagicLink() {
  const password = await readSystemPassword();
  const resp = await fetch(`${API_BASE}/auth/magic/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => resp.statusText);
    throw new Error(`magic-link mint failed (${resp.status}): ${detail.slice(0, 200)}`);
  }
  const data = await resp.json();
  return `${DASHBOARD_URL}/auth/magic/${data.magic_id}`;
}

function browserOpener() {
  return process.platform === "darwin" ? "open"
    : process.platform === "win32" ? "start"
    : "xdg-open";
}

function openInBrowser(url) {
  spawn(browserOpener(), [url], { detached: true, stdio: "ignore" }).unref();
}

/** Run `onEnter()` every time the user presses Return on stdin. Resolves
 *  when the input stream closes (Ctrl+D / EOF). One persistent readline
 *  is intentional — recreating it after each line closes process.stdin,
 *  which makes the next createInterface fire `close` immediately and
 *  silently kills the loop. */
function loopOnEnter(onEnter) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin });
    rl.on("line", () => {
      Promise.resolve(onEnter()).catch((e) => log.error(`retry failed: ${e.message}`));
    });
    rl.on("close", () => resolve());
  });
}

async function ensureInstalled() {
  const state = await loadState();
  if (!state) {
    log.error("Delphi isn't installed yet. Run `npx @synsci/delphi init` first.");
    process.exit(1);
  }
  return state;
}

export async function runStart() {
  const state = await ensureInstalled();
  await spinner("starting Delphi", () =>
    composeUp({ build: false, profiles: state.profiles || [], silent: true, withGpu: !!state.useGpu }),
  );
  await spinner("waiting for API", () => waitForHealth());
  log.success(`up at ${pc.cyan(API_BASE)}`);
}

export async function runStop() {
  const state = await ensureInstalled();
  // `down` with the saved profiles removes everything we started; without
  // them, profile-gated containers (e.g. frontend) are left orphaned.
  await spinner("stopping Delphi", () =>
    composeDown({ profiles: state.profiles || [], silent: true, withGpu: !!state.useGpu }),
  );
}

export async function runStatus() {
  banner();
  const state = await ensureInstalled();

  let healthOk = false;
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2_000) });
    healthOk = res.ok;
  } catch {
    healthOk = false;
  }

  const services = await composeStatus({ profiles: state.profiles || [], withGpu: !!state.useGpu });

  log.raw(`  Status:    ${healthOk ? pc.green("healthy") : pc.red("not responding")}`);
  log.raw(`  API:       ${pc.cyan(API_BASE)}`);
  log.raw(`  API key:   ${pc.dim(state.apiKeyPreview ? state.apiKeyPreview + "…" : "(not set)")}`);
  log.raw(`  Embedding: ${pc.dim(state.embeddingChoice || "(unknown)")}`);
  log.raw(`  Clients:   ${pc.dim((state.clients || []).join(", ") || "(none)")}`);
  console.log();

  if (services.length) {
    log.raw(pc.bold("Containers:"));
    for (const s of services) {
      const name = s.Name || s.Service || "?";
      const stateStr = s.State || s.Status || "?";
      log.raw(`  ${name.padEnd(20)} ${pc.dim(stateStr)}`);
    }
  } else {
    log.dim("No containers running.");
  }
}

export async function runLogs({ follow = false, services = [] } = {}) {
  const state = await ensureInstalled();
  await composeLogs({ follow, services, profiles: state.profiles || [], withGpu: !!state.useGpu });
}

/** Whether all containers we need are running AND the api reports
 *  every subsystem ready. Two checks back-to-back:
 *
 *    1. `docker compose ps` — confirms postgres / api / frontend are
 *       all in the `running` state. Fast (~50ms), catches the obvious.
 *    2. `GET /backend-health` — deep readiness probe; validates the api
 *       can actually serve real traffic (DB pool live, MCP session
 *       manager started). Catches the case where a container is
 *       `running` but the process inside is broken — saves the user
 *       from opening a dashboard whose every click 500s.
 *
 *  Either failing → fall through to the cold-path docker rebuild. */
async function dashboardFullyUp(profiles, { withGpu = false } = {}) {
  try {
    const services = await composeStatus({ profiles, withGpu });
    if (!services.length) return false;
    const required = ["postgres", "api", "frontend"];
    const byService = new Map(services.map((s) => [s.Service, s]));
    for (const name of required) {
      const s = byService.get(name);
      if (!s) return false;
      const state = (s.State || "").toLowerCase();
      if (state !== "running") return false;
    }
    const res = await fetch(`${API_BASE}/backend-health`, {
      signal: AbortSignal.timeout(3_000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

/** Open the dashboard in the user's default browser, ensuring the stack is up. */
export async function runOpen() {
  const state = await ensureInstalled();

  // Opening the dashboard implies the dashboard profile, even if the user
  // initially picked the agent path. Persist so `delphi start` keeps it on.
  const profiles = Array.from(new Set([...(state.profiles || []), "dashboard"]));
  if (profiles.length !== (state.profiles || []).length) {
    const { saveState } = await import("./env.js");
    await saveState({ ...state, profiles });
  }

  // Warm path: stack is already up + healthy. Skip every docker call —
  // they're all no-ops, but `compose build` + `compose up -d` can take
  // 5–10s just evaluating the compose file, recreating the api on any
  // config drift, etc. The whole point of `delphi open` on a running
  // install should be a near-instant browser launch.
  const fullyUp = await dashboardFullyUp(profiles, { withGpu: !!state.useGpu });

  if (!fullyUp) {
    // Cold or partial start. Phase the docker calls so the user sees
    // what's happening: pulling base images (network), building local
    // images (CPU), starting containers, waiting for /health.
    let healthy = false;
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2_000) });
      healthy = res.ok;
    } catch {
      healthy = false;
    }
    if (!healthy) {
      await spinner("pulling base images", () =>
        composePull({ profiles, silent: true, withGpu: !!state.useGpu }),
      );
    }
    await spinner("building dashboard image", () =>
      composeBuild({ profiles, silent: true, withGpu: !!state.useGpu }),
    );
    await spinner("starting containers", () =>
      composeUp({ build: false, profiles, silent: true }),
    );
    // `up -d` can recreate the api container when compose detects a
    // config change even if it was healthy a moment ago — wait for
    // /health unconditionally before minting a magic link, or the
    // fetch races the 2–3s api restart and looks like "fetch failed".
    await spinner("waiting for API", () => waitForHealth());
  }

  // Auto-sign-in via magic link. The token is opaque, single-use, 60s
  // TTL, and never printed to stdout — it lives in the URL the OS hands
  // to the browser and nowhere else the user can see.
  let magicUrl;
  try {
    magicUrl = await mintMagicLink();
  } catch (e) {
    log.warn(`auto-sign-in unavailable: ${e.message}`);
    log.dim(`  open ${pc.cyan(DASHBOARD_URL)} manually and use the password you set at install time.`);
    return;
  }
  openInBrowser(magicUrl);
  log.success("dashboard launched");
  log.dim("  if it didn't open, press enter to retry · ctrl-c to exit");

  // Loop on Enter so the user can keep retrying if the browser doesn't
  // come up (or they closed the window). Each retry mints a fresh magic
  // id since the previous one is single-use. EOF / Ctrl+D ends the loop.
  await loopOnEnter(async () => {
    openInBrowser(await mintMagicLink());
  });
}

export async function runUninstall() {
  const state = await ensureInstalled();
  log.warn("This will tear down containers AND delete the local Delphi data volume.");
  const { confirm } = await import("@inquirer/prompts");
  const ok = await confirm({ message: "Continue?", default: false });
  if (!ok) return;
  await spinner("removing Delphi", () =>
    composeDown({ removeVolumes: true, profiles: state.profiles || [], silent: true, withGpu: !!state.useGpu }),
  );
  log.dim("source dir kept at ~/.synsci/delphi/source");
}
