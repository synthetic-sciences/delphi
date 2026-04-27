import fs from "node:fs/promises";
import { confirm } from "@inquirer/prompts";
import pc from "picocolors";
import { log, banner, spinner } from "./log.js";
import { loadDotenv } from "./dotenv.js";
import { applyConfig, EMBEDDING_PROFILES, loadState } from "./env.js";
import { ENV_FILE } from "./paths.js";
import { runReload } from "./reload.js";
import { API_BASE } from "./health.js";
import { pickProvider, collectProviderConfig, promptSystemPassword } from "./prompts.js";

const ENV_BACKUP = `${ENV_FILE}.bak`;
// Cold model loads (a fresh HF download, sentence-transformers init) can
// take a while. Bound the probe so a hung restart doesn't lock the CLI
// forever; treat anything over this as a failed config and roll back.
const PROBE_TIMEOUT_MS = 90_000;

/** GET /backend-health?probe=embeddings — runs a real embed_query("ping")
 *  end-to-end. Returns the parsed JSON or throws on network/timeout. */
async function probeEmbeddings() {
  const resp = await fetch(`${API_BASE}/backend-health?probe=embeddings`, {
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
    await runReload({ quiet: true });
    log.error("rollback complete. .env unchanged from before this run.");
    log.dim("  Re-run `delphi config` after fixing the issue (bad key, model id, network, …).");
    process.exit(1);
  }

  // Probe succeeded — keep the new .env, drop the backup.
  await fs.rm(ENV_BACKUP, { force: true });
  log.success("config updated");
}
