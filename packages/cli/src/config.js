import { confirm } from "@inquirer/prompts";
import pc from "picocolors";
import { log, banner, spinner } from "./log.js";
import { loadDotenv } from "./dotenv.js";
import { applyConfig, EMBEDDING_PROFILES, loadState } from "./env.js";
import { composeRestart } from "./docker.js";
import { waitForHealth } from "./health.js";
import { pickProvider, collectProviderConfig, promptSystemPassword } from "./prompts.js";

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

  // ── WRITE + RESTART ─────────────────────────────────────────────────
  await spinner("writing config", () => applyConfig(updates));
  await spinner("restarting services", () =>
    composeRestart({ services: ["api", "worker"], silent: true }),
  );
  await spinner("waiting for API", () => waitForHealth());
  log.success("config updated");
}
