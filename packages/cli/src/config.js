import fs from "node:fs/promises";
import { confirm } from "@inquirer/prompts";
import pc from "picocolors";
import { log, banner, spinner } from "./log.js";
import { loadDotenv } from "./dotenv.js";
import { applyConfig, saveState, EMBEDDING_PROFILES, loadState } from "./env.js";
import { ENV_FILE } from "./paths.js";
import { runReload } from "./reload.js";
import { apiBase } from "./health.js";
import { detectGpu } from "./system.js";
import { pickProvider, collectProviderConfig, promptSystemPassword, pickDevice } from "./prompts.js";

const ENV_BACKUP = `${ENV_FILE}.bak`;
// Cold model loads dominate the validation budget. Worst case: empty
// HF cache + new CUDA init + 1+ GB safetensors download = ~3 min on a
// typical broadband connection. Bound the probe so a genuinely hung
// restart doesn't lock the CLI forever, but give honest cold loads
// enough room to finish.
const PROBE_TIMEOUT_MS = 300_000;  // 5 minutes

/** GET /backend-health?probe=embeddings — runs a real embed_query("ping")
 *  end-to-end. Returns the parsed JSON or throws on network/timeout. */
async function probeEmbeddings() {
  const resp = await fetch(`${apiBase()}/backend-health?probe=embeddings`, {
    signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
  });
  // We accept both 200 (ready) and 503 (not ready, payload still has the
  // failing check) — the JSON body is what we care about.
  return resp.json();
}

const SECRET_KEYS = new Set([
  "SERVER_SECRET",
  "POSTGRES_PASSWORD",
  "DATABASE_URL",
  "SYSTEM_PASSWORD",
  "GEMINI_API_KEY",
  "OPENAI_API_KEY",
  "HF_TOKEN",
  "TOKEN_ENCRYPTION_KEY",
]);

/** Map an EMBEDDING_PROFILES entry's `env.EMBEDDING_PROVIDER` value back to
 *  the profile key the CLI uses (`local_balanced` etc.). */
function providerKeyFromEnv(envProvider) {
  for (const [key, profile] of Object.entries(EMBEDDING_PROFILES)) {
    if (profile.env?.EMBEDDING_PROVIDER === envProvider) return key;
  }
  return null;
}

/** Format a value for the diff summary, masking anything secret-shaped so
 *  pasting the terminal log doesn't leak credentials. */
function display(key, value) {
  if (value === undefined || value === null) return pc.dim("(unset)");
  if (value === "") return pc.dim("(empty)");
  if (SECRET_KEYS.has(key)) {
    if (value.length <= 4) return pc.dim("••••");
    return pc.dim(`••••${value.slice(-4)}`);
  }
  return pc.cyan(value);
}

/**
 * Interactive editor for the install-time choices. Reads the current
 * `.env`, walks the same prompts as `init`, computes a diff, prints it,
 * confirms, writes the file atomically, and restarts api + worker.
 */
export async function runConfig() {
  banner();

  const state = await loadState();
  if (!state) {
    log.error("Delphi isn't installed yet. Run `npx @synsci/delphi init` first.");
    process.exit(1);
  }

  const parsed = await loadDotenv((await import("./paths.js")).ENV_FILE);
  if (!parsed) {
    log.error(".env not found. Re-run `npx @synsci/delphi init --force`.");
    process.exit(1);
  }
  const currentMap = parsed.map;

  // ── PROVIDER + KEYS + MODEL ─────────────────────────────────────────
  const currentProvider = providerKeyFromEnv(currentMap.get("EMBEDDING_PROVIDER")) || "local_balanced";
  const newProviderKey = await pickProvider({ current: currentProvider });
  const profile = EMBEDDING_PROFILES[newProviderKey];
  const providerEnv = await collectProviderConfig(profile, { existing: currentMap });

  // ── GPU DEVICE (Local provider only) ────────────────────────────────
  // Re-run the same detect+prompt cycle init does. Lets users pick up a
  // newly-installed nvidia-container-toolkit, or downgrade to CPU after
  // they pulled the GPU for another workload, without re-installing.
  let useGpu = !!state.useGpu;
  if (profile.kind === "local") {
    const gpu = await detectGpu();
    if (gpu.available) {
      const device = await pickDevice({
        gpuName: gpu.gpu,
        current: currentMap.get("EMBEDDING_DEVICE"),
      });
      useGpu = device === "cuda";
      providerEnv.EMBEDDING_DEVICE = device;
    } else if (gpu.hostGpu) {
      log.warn(`detected ${gpu.hostGpu} but Docker still isn't configured to pass GPUs.`);
      log.dim(`  Run:  ${gpu.installHint}`);
      log.dim("        then re-run delphi config to enable GPU acceleration.");
      // Force CPU since GPU isn't reachable from the container.
      useGpu = false;
      providerEnv.EMBEDDING_DEVICE = "cpu";
    }
  } else {
    // Switching off Local — GPU choice is moot.
    useGpu = false;
  }

  // ── DASHBOARD PASSWORD ──────────────────────────────────────────────
  const newPassword = await promptSystemPassword({
    existing: currentMap.get("SYSTEM_PASSWORD"),
  });

  // ── BUILD UPDATE MAP ────────────────────────────────────────────────
  // Profile-level non-secret defaults (DIMENSION, BATCH_SIZE, DEVICE)
  // come from EMBEDDING_PROFILES.env. User answers (keys, model)
  // override them in providerEnv. Together they define the new state of
  // the install-time-managed keys.
  const updates = {
    EMBEDDING_PROVIDER: profile.env.EMBEDDING_PROVIDER,
    ...profile.env,
    ...providerEnv,
  };
  if (newPassword) {
    updates.SYSTEM_PASSWORD = newPassword;
  }

  // Compute diff against the current .env. Only keys whose value actually
  // changes show up; everything else is left exactly as it was.
  const changes = [];
  for (const [key, after] of Object.entries(updates)) {
    const before = currentMap.get(key);
    if (before === after) continue;
    changes.push({ key, before, after });
  }
  // GPU pseudo-key — not in .env (it's a compose-flag concern), but still a
  // user-visible change that requires a force-recreate of the api/worker
  // containers to apply the resource reservation.
  const gpuChanged = !!state.useGpu !== useGpu;
  if (gpuChanged) {
    changes.push({
      key: "GPU acceleration",
      before: state.useGpu ? "enabled" : "disabled",
      after: useGpu ? "enabled" : "disabled",
    });
  }

  if (changes.length === 0) {
    log.info("No changes — config matches current .env.");
    return;
  }

  // ── PREVIEW + CONFIRM ───────────────────────────────────────────────
  console.log();
  log.raw(pc.bold("Changes:"));
  for (const { key, before, after } of changes.sort((a, b) => a.key.localeCompare(b.key))) {
    log.raw(`  ${key.padEnd(22)} ${display(key, before)} ${pc.dim("→")} ${display(key, after)}`);
  }
  console.log();

  const ok = await confirm({ message: "Apply these changes?", default: true });
  if (!ok) {
    log.info("Cancelled. Nothing written.");
    return;
  }

  // ── TRANSACTIONAL APPLY ─────────────────────────────────────────────
  // 1. Snapshot the current .env so we can roll back if the new config
  //    fails an end-to-end embed probe.
  // 2. Write the new .env.
  // 3. Restart api+worker (delegates to runReload).
  // 4. Run /backend-health?probe=embeddings — actual embed_query call.
  // 5. On success: drop the backup, declare success.
  //    On failure: restore .env from backup, restart again, surface
  //    the provider's error so the user can fix and retry.
  await spinner("backing up current config", () =>
    fs.copyFile(ENV_FILE, ENV_BACKUP),
  );
  await spinner("writing config", () => applyConfig(updates));

  // Persist GPU choice into state.json BEFORE recreate so runReload
  // applies the right docker-compose.gpu.yml override flag.
  if (gpuChanged) {
    await saveState({ ...state, useGpu });
  }

  // runReload now does `compose up --force-recreate` (not `restart`),
  // so it picks up both the .env changes AND any compose-level config
  // changes (GPU resource reservation flip). Single code path for both
  // env-only changes and useGpu changes.
  await runReload({ quiet: true });

  let probeResult;
  try {
    probeResult = await spinner("validating new config (cold model load can take ~30s)", () =>
      probeEmbeddings(),
    );
  } catch (e) {
    probeResult = { ready: false, checks: { embedding_call: { ok: false, error: e.message } } };
  }

  const probeFailed =
    !probeResult ||
    probeResult.ready === false ||
    !probeResult.checks?.embedding_call?.ok;

  if (probeFailed) {
    const detail = probeResult?.checks?.embedding_call?.error || "unknown error";
    log.error(`new config failed validation: ${detail}`);
    log.warn("rolling back to previous config…");
    await spinner("restoring previous .env", () =>
      fs.rename(ENV_BACKUP, ENV_FILE),
    );
    // Roll state.useGpu back too — we may have updated it before the
    // validation ran, so without this `delphi start` would still pass
    // the GPU compose flag for a config that was just rolled back.
    if (gpuChanged) {
      await saveState({ ...state });
      // If the failed config tried to ENABLE GPU, the live containers
      // were force-recreated with the GPU override. Recreate again with
      // the original (CPU) compose to match the rolled-back state.
      if (useGpu && !state.useGpu) {
        const { composeUp } = await import("./docker.js");
        await spinner("recreating containers without GPU", () =>
          composeUp({
            services: ["api", "worker"],
            profiles: state.profiles || [],
            withGpu: false,
            forceRecreate: true,
            silent: true,
          }),
        );
      }
    }
    await runReload({ quiet: true });
    log.error("rollback complete. .env unchanged from before this run.");
    log.dim("  Re-run `delphi config` after fixing the issue (bad key, model id, network, …).");
    process.exit(1);
  }

  // Probe succeeded — keep the new .env, drop the backup.
  await fs.rm(ENV_BACKUP, { force: true });
  log.success("config updated");
}
