import fs from "node:fs/promises";
import readline from "node:readline";
import pc from "picocolors";
import { spawn } from "node:child_process";
import { log, banner, spinner } from "./log.js";
import { composePull, composeBuild, composeUp, composeDown, composeStatus, composeLogs } from "./docker.js";
import { loadState } from "./env.js";
import path from "node:path";
import os from "node:os";
import { ENV_FILE, ROOT } from "./paths.js";
import { run } from "./system.js";
import { waitForHealth, API_BASE } from "./health.js";

/** Read the frontend host port out of .env. Defaults to 3000 when
 *  unset (older installs predating port-discovery; existing user
 *  hand-edits). */
async function dashboardUrl() {
  try {
    const text = await fs.readFile(ENV_FILE, "utf-8");
    const m = text.match(/^FRONTEND_PORT=(.+)$/m);
    const port = m ? m[1].trim() : "3000";
    return `http://localhost:${port}`;
  } catch {
    return "http://localhost:3000";
  }
}

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
  return `${await dashboardUrl()}/auth/magic/${data.magic_id}`;
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
    log.dim(`  open ${pc.cyan(await dashboardUrl())} manually and use the password you set at install time.`);
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

/** Best-effort `rm -rf` that swallows ENOENT — uninstall should be
 *  idempotent even if a previous partial uninstall already removed the
 *  target. Anything else (perms, EBUSY) re-raises so the user sees it. */
async function rmIfExists(p) {
  try {
    await fs.rm(p, { recursive: true, force: true });
  } catch (e) {
    if (e.code !== "ENOENT") throw e;
  }
}

export async function runUninstall() {
  // Don't gate on ensureInstalled. Half-finished installs (compose
  // failed mid-way, no state.json was ever written) leave behind
  // orphan containers + volumes that uninstall must still clean up.
  // We treat anything we can find — source dir, named volumes,
  // built images, MCP entries — as a target.
  const state = (await loadState()) || {};

  const launcherCandidates = [
    path.join(os.homedir(), ".local", "bin", "delphi"),
    "/usr/local/bin/delphi",
  ];
  const installDir = ROOT;
  const sourceExists = await fs
    .access(path.join(installDir, "source", "docker-compose.yml"))
    .then(() => true)
    .catch(() => false);

  console.log();
  log.warn(pc.bold("This permanently removes ALL Delphi state on this machine."));
  log.dim("  Containers + volumes (pgdata + hf-cache) + network");
  log.dim("  Built images: source-api, source-worker, source-frontend");
  log.dim(`  Install dir: ${installDir}`);
  log.dim(`  Launcher symlink: ${launcherCandidates.join(" or ")}`);
  log.dim("  Claude Code MCP registration (synsci-delphi)");
  console.log();

  const { confirm } = await import("@inquirer/prompts");
  const ok = await confirm({ message: "Continue?", default: false });
  if (!ok) {
    log.info("Cancelled. Nothing removed.");
    return;
  }

  // 1. Containers + volumes + network. compose down -v needs the source
  // dir's docker-compose.yml to know what to clean up. If the user
  // half-completed an install (Aayam's case — pgdata volume created,
  // install bailed at composeUp before writing state.json) we still
  // want to run this. If the source dir is gone too, fall through to
  // the explicit `docker volume rm` / `docker rm` step below.
  if (sourceExists) {
    await spinner("tearing down containers + volumes", () =>
      composeDown({
        removeVolumes: true,
        profiles: ["dashboard"],     // catch frontend even if state.profiles dropped it
        silent: true,
        withGpu: !!state.useGpu,
      }),
    );
  }

  // 1b. Belt + suspenders for orphan resources that compose can miss
  // (e.g. half-created project from a prior failed install whose
  // compose file disappeared, leaving named resources behind). All
  // best-effort — `docker rm` errors when the target's already gone.
  await spinner("removing orphan containers + volumes", async () => {
    await run("docker", [
      "rm", "-f",
      "source-api-1", "source-worker-1", "source-frontend-1", "source-postgres-1",
    ], { silent: true });
    await run("docker", [
      "volume", "rm", "source_pgdata", "source_hf-cache",
    ], { silent: true });
    await run("docker", ["network", "rm", "source_default"], { silent: true });
  });

  // 2. Built images. Skipping these would leave ~12 GB of stale image
  // data on the user's disk after they thought they uninstalled.
  // Failures are non-fatal — image may already be gone, name may not
  // match if compose project was named differently.
  await spinner("removing built images", async () => {
    const images = ["source-api", "source-worker", "source-frontend"];
    await run("docker", ["rmi", "-f", ...images], { silent: true });
  });

  // 3. Install dir (source clone + state.json + bin/delphi script).
  await spinner("removing install dir", () => rmIfExists(installDir));

  // 4. Launcher symlinks. Both candidates if present.
  await spinner("removing launcher", async () => {
    for (const launcher of launcherCandidates) {
      await rmIfExists(launcher);
    }
  });

  // 5. Claude Code MCP entry. Best-effort — `claude` may not be on
  // PATH (user uninstalled CC) or the entry may already be gone.
  await spinner("removing Claude Code MCP entry", async () => {
    await run("claude", ["mcp", "remove", "synsci-delphi", "--scope", "user"], { silent: true });
    await run("claude", ["mcp", "remove", "synsci-delphi", "--scope", "project"], { silent: true });
  });

  console.log();
  log.success("Delphi removed.");
  log.dim("  HuggingFace model cache and pgvector data are gone.");
  log.dim("  Run `npx @synsci/delphi` to install fresh.");
}
