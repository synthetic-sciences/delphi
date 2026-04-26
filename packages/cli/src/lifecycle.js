import pc from "picocolors";
import { spawn } from "node:child_process";
import { log, banner } from "./log.js";
import { composeUp, composeDown, composeStatus, composeLogs } from "./docker.js";
import { loadState } from "./env.js";
import { waitForHealth, API_BASE } from "./health.js";

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
  log.step("Starting Delphi");
  await composeUp({ build: false, profiles: state.profiles || [] });
  await waitForHealth();
  log.success(`up at ${API_BASE}`);
}

export async function runStop() {
  const state = await ensureInstalled();
  log.step("Stopping Delphi");
  // `down` with the saved profiles removes everything we started; without
  // them, profile-gated containers (e.g. frontend) are left orphaned.
  await composeDown({ profiles: state.profiles || [] });
  log.success("stopped");
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

  const services = await composeStatus({ profiles: state.profiles || [] });

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
  await composeLogs({ follow, services, profiles: state.profiles || [] });
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

  // Make sure the stack (incl. dashboard) is running before launching the browser.
  let healthy = false;
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(2_000) });
    healthy = res.ok;
  } catch {
    healthy = false;
  }
  // Even if api/health is up, frontend may not be — `up -d` is a no-op for
  // already-running services but will start the dashboard if it isn't.
  if (!healthy) log.info("starting Delphi (it isn't running)…");
  else log.info("starting dashboard…");
  await composeUp({ build: true, profiles });
  if (!healthy) await waitForHealth();

  const url = "http://localhost:3000";
  const cmd =
    process.platform === "darwin" ? "open"
    : process.platform === "win32" ? "start"
    : "xdg-open";
  spawn(cmd, [url], { detached: true, stdio: "ignore" }).unref();
  log.success(`opened ${pc.cyan(url)}`);
}

export async function runUninstall() {
  const state = await ensureInstalled();
  log.warn("This will tear down containers AND delete the local Delphi data volume.");
  const { confirm } = await import("@inquirer/prompts");
  const ok = await confirm({ message: "Continue?", default: false });
  if (!ok) return;
  await composeDown({ removeVolumes: true, profiles: state.profiles || [] });
  log.success("Delphi removed (source dir kept at ~/.synsci/delphi/source).");
}
