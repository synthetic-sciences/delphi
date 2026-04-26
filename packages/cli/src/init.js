import { select, checkbox, confirm, password } from "@inquirer/prompts";
import pc from "picocolors";
import { log, banner, spinner } from "./log.js";
import { dockerHealthy, which } from "./system.js";
import { ensureSource } from "./source.js";
import { writeEnv, saveState, loadState, EMBEDDING_PROFILES } from "./env.js";
import { composeUp } from "./docker.js";
import { waitForHealth, bootstrap, API_BASE } from "./health.js";
import {
  detectInstalledClients,
  installToClients,
  CLIENT_LABELS,
} from "./clients.js";
import { installLauncher } from "./launcher.js";

const FLOWS = {
  agent: "Add to my coding agent (Claude Code, Cursor, Windsurf, Claude Desktop)",
  index: "Run my own index — pick a provider, attach an API key, get a dashboard",
};

async function pickProvider({ apiOnly = false } = {}) {
  const choices = Object.entries(EMBEDDING_PROFILES).map(([value, p]) => {
    const disabled = !p.available
      ? pc.dim("(coming soon)")
      : apiOnly && p.kind !== "api" && value !== "local_balanced"
      ? false
      : false;
    return { value, name: p.label, disabled };
  });

  return select({
    message: "Which embeddings provider?",
    choices,
    default: apiOnly ? "gemini" : "local_balanced",
  });
}

async function maybePromptApiKey(profile) {
  if (profile.kind !== "api") return {};
  const key = await password({
    message: `Paste your ${profile.keyEnvVar}: ${pc.dim("(get one at " + profile.keyHint + ")")}`,
    mask: "•",
    validate: (v) => (v && v.trim().length > 8 ? true : "That doesn't look like an API key."),
  });
  return { [profile.keyEnvVar]: key.trim() };
}

export async function runInit({ force = false } = {}) {
  banner();

  const existing = await loadState();
  if (existing && !force) {
    log.warn(`Found an existing install at ${pc.cyan(existing.sourceDir || "~/.synsci/delphi")}`);
    const reuse = await confirm({
      message: "Reuse existing install? (No will reconfigure from scratch)",
      default: true,
    });
    if (reuse) {
      log.info("Skipping setup. Run `delphi status` for current state.");
      return;
    }
  }

  // Path selection
  const flow = await select({
    message: "How would you like to use Delphi?",
    choices: Object.entries(FLOWS).map(([value, name]) => ({ value, name })),
    default: "agent",
  });

  // ── AGENT PATH ─────────────────────────────────────────────────────────
  let chosenClients = [];
  let embeddingChoice = "local_balanced";
  let apiKeys = {};

  if (flow === "agent") {
    const detected = await detectInstalledClients();
    chosenClients = await checkbox({
      message: "Which AI tools should I configure?",
      choices: Object.entries(CLIENT_LABELS).map(([value, label]) => ({
        value,
        name: detected[value] ? `${label} ${pc.green("(detected)")}` : label,
        checked: !!detected[value],
      })),
    });
    if (chosenClients.length === 0) {
      log.warn("No clients selected. Continuing with the dashboard only.");
    }
  } else {
    // ── INDEX PATH ────────────────────────────────────────────────────────
    embeddingChoice = await pickProvider({ apiOnly: true });
    const profile = EMBEDDING_PROFILES[embeddingChoice];
    apiKeys = await maybePromptApiKey(profile);
  }

  // Pre-flight checks
  log.step("Pre-flight checks");
  const docker = await dockerHealthy();
  if (!docker.ok) {
    log.error(`Docker isn't reachable: ${docker.reason}`);
    log.dim("Install Docker Desktop from https://www.docker.com/products/docker-desktop/ and try again.");
    process.exit(1);
  }
  log.success("Docker is running");
  if (!(await which("git"))) {
    log.error("git not found on PATH. Install git and re-run.");
    process.exit(1);
  }
  log.success("git is available");

  // Source + .env
  log.step("Fetching source");
  await ensureSource();

  log.step("Writing config");
  const secrets = await writeEnv({ embeddingChoice, apiKeys });
  log.success(`wrote ~/.synsci/delphi/source/.env`);

  // Spin up
  log.step("Starting Docker stack (first run pulls images and downloads models — a few minutes)");
  await composeUp({ build: true });
  log.success("services started");

  // Health
  await spinner("waiting for the API to come online", () => waitForHealth());

  // Bootstrap
  log.step("Minting an API key");
  const minted = await bootstrap({ password: secrets.systemPassword });
  log.success(`key ${pc.bold(minted.key_preview + "…")} created`);

  // MCP wiring (agent path only)
  let installResults = {};
  if (chosenClients.length) {
    log.step("Configuring AI tools");
    installResults = await installToClients(chosenClients, {
      apiKey: minted.api_key,
      apiUrl: API_BASE,
    });
    for (const [id, r] of Object.entries(installResults)) {
      if (r.ok) log.success(`${CLIENT_LABELS[id]} ${pc.dim("←")} ${pc.dim(r.path)}`);
      else log.error(`${CLIENT_LABELS[id]}: ${r.error}`);
    }
  }

  // Install the `delphi` launcher
  const launcher = await installLauncher();

  // Persist state
  await saveState({
    version: 1,
    installedAt: new Date().toISOString(),
    flow,
    embeddingChoice,
    apiKeyPreview: minted.key_preview,
    apiUrl: API_BASE,
    clients: Object.keys(installResults),
    launcher,
  });

  // Final report
  console.log();
  log.raw(pc.bold(pc.green("All set.")));
  log.dim("───────────────────────────────────────────────");
  log.raw(`  Dashboard:       ${pc.cyan("http://localhost:3000")}`);
  log.raw(`  API:             ${pc.cyan(API_BASE)}`);
  log.raw(`  API key:         ${pc.cyan(minted.api_key)}  ${pc.dim("(saved into MCP configs)")}`);
  log.raw(`  Dashboard login: password ${pc.cyan(secrets.systemPassword)}`);
  log.raw(`  Embeddings:      ${pc.cyan(EMBEDDING_PROFILES[embeddingChoice].label)}`);
  log.dim("───────────────────────────────────────────────");

  if (launcher.installed) {
    log.raw(pc.bold("Next:") + ` type ${pc.cyan("delphi")} in any terminal to open the dashboard.`);
    if (launcher.pathHint) log.dim(`  ${launcher.pathHint}`);
  }
  if (chosenClients.length) {
    log.raw(`       Then restart your AI tool — Delphi will appear as an MCP server.`);
  }
  log.dim("Lifecycle: `delphi status | logs | stop | start | open`");
  console.log();
}
