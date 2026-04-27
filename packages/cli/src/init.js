import { select, checkbox, confirm, password, input } from "@inquirer/prompts";
import pc from "picocolors";
import { log, banner, spinner } from "./log.js";
import { dockerHealthy, which } from "./system.js";
import { ensureSource } from "./source.js";
import { writeEnv, saveState, loadState, EMBEDDING_PROFILES } from "./env.js";
import { composePull, composeBuild, composeUp } from "./docker.js";
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

async function pickProvider() {
  const choices = Object.entries(EMBEDDING_PROFILES).map(([value, p]) => ({
    value,
    name: p.label,
    disabled: p.available ? false : pc.dim("(coming soon)"),
  }));

  return select({
    message: "Which embeddings provider?",
    choices,
    default: "local_balanced",
  });
}

/**
 * Collect provider-specific config (API key, optional HF_TOKEN, model name)
 * via prompts. Returns an env-var object that gets merged into the .env
 * file. Order of prompts: required key → optional key → model picker.
 */
async function collectProviderConfig(profile) {
  const env = {};

  // Required key (Gemini, OpenAI).
  if (profile.keyEnvVar) {
    const key = await password({
      message: `Paste your ${profile.keyEnvVar}: ${pc.dim("(get one at " + profile.keyHint + ")")}`,
      mask: "•",
      validate: (v) => (v && v.trim().length > 8 ? true : "That doesn't look like a real key."),
    });
    env[profile.keyEnvVar] = key.trim();
  }

  // Optional key (HF_TOKEN for the local provider — only needed for gated
  // models). Empty input skips the var entirely.
  if (profile.optionalKeyEnvVar) {
    const key = await password({
      message:
        `${profile.optionalKeyEnvVar} ${pc.dim("(optional — " + profile.optionalKeyReason + "; get one at " + profile.optionalKeyHint + ")")}\n  ` +
        pc.dim("Press enter to skip"),
      mask: "•",
    });
    if (key.trim()) {
      env[profile.optionalKeyEnvVar] = key.trim();
    }
  }

  // Model picker. Confirm-default → either keep the suggestion or type a
  // custom model id. We split this in two steps (vs a single input with a
  // pre-filled default) so the choice is explicit and the suggested model
  // is shown without requiring the user to delete it.
  if (profile.promptModel) {
    const useDefault = await confirm({
      message: `Use the default model? ${pc.dim("(" + profile.defaultModel + ")")}`,
      default: true,
    });
    if (useDefault) {
      env.EMBEDDING_MODEL = profile.defaultModel;
    } else {
      const model = await input({
        message: `Enter the model id ${pc.dim("(" + profile.modelHint + ")")}`,
        validate: (v) =>
          v && v.trim().includes("/")
            ? true
            : "Use the form `org/repo` (e.g. BAAI/bge-base-en-v1.5).",
      });
      env.EMBEDDING_MODEL = model.trim();
    }
  }

  return env;
}

async function promptSystemPassword() {
  const pw = await password({
    message: `Set a dashboard password ${pc.dim("(used to log in at http://localhost:3000 and to bootstrap the API key)")}`,
    mask: "•",
    validate: (v) => (v && v.length >= 8 ? true : "At least 8 characters."),
  });
  return pw;
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

  // ── CLIENT SELECTION (agent path only) ────────────────────────────────
  let chosenClients = [];

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
  }

  // ── PROVIDER + MODEL + KEY (both flows) ────────────────────────────────
  // Both paths need an embedding provider — agent users still want a choice
  // between local-CPU and a hosted API (faster on small machines, no model
  // download). Only the index path wires the dashboard.
  const embeddingChoice = await pickProvider();
  const profile = EMBEDDING_PROFILES[embeddingChoice];
  const providerConfig = await collectProviderConfig(profile);

  // ── DASHBOARD PASSWORD ────────────────────────────────────────────────
  // Always prompt: it's used both as the dashboard login and as the
  // bootstrap secret that mints the CLI's API key further down.
  const systemPassword = await promptSystemPassword();

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
  const sourceInfo = await spinner("fetching source", () => ensureSource());
  if (sourceInfo.sha) {
    log.dim(`  source @ ${sourceInfo.sha}${sourceInfo.stale ? " (offline — using cached checkout)" : ""}`);
  }

  const secrets = await spinner("writing config", () =>
    writeEnv({ embeddingChoice, providerConfig, systemPassword }),
  );

  // Spin up. Agent-path users don't need the dashboard, so skip building the
  // frontend image entirely — saves ~150MB and lets the api/worker images
  // export without competing for the same Docker VM disk.
  const profiles = flow === "index" ? ["dashboard"] : [];

  // Split the docker startup into named phases so the user can see exactly
  // which step is slow. Each `compose` invocation is silent under a spinner;
  // on failure the helper surfaces stderr in the thrown error.
  log.step("Starting services");
  await spinner("pulling base images (~200MB on first run)", () =>
    composePull({ profiles, silent: true }),
  );
  await spinner("building images (api · worker" + (flow === "index" ? " · frontend" : "") + ")", () =>
    composeBuild({ profiles, silent: true }),
  );
  await spinner("starting containers", () =>
    composeUp({ build: false, profiles, silent: true }),
  );

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
    profiles,
    embeddingChoice,
    apiKeyPreview: minted.key_preview,
    apiUrl: API_BASE,
    clients: Object.keys(installResults),
    launcher,
  });

  // Final report
  const dashboardOn = profiles.includes("dashboard");
  console.log();
  log.raw(pc.bold(pc.green("All set.")));
  log.dim("───────────────────────────────────────────────");
  if (dashboardOn) {
    log.raw(`  Dashboard:       ${pc.cyan("http://localhost:3000")}`);
  }
  log.raw(`  API:             ${pc.cyan(API_BASE)}`);
  log.raw(`  API key:         ${pc.cyan(minted.api_key)}  ${pc.dim("(saved into MCP configs)")}`);
  if (dashboardOn) {
    log.raw(`  Dashboard login: ${pc.dim("the password you just set")}`);
  }
  log.raw(`  Embeddings:      ${pc.cyan(EMBEDDING_PROFILES[embeddingChoice].label)}`);
  if (providerConfig.EMBEDDING_MODEL) {
    log.raw(`  Model:           ${pc.cyan(providerConfig.EMBEDDING_MODEL)}`);
  }
  log.dim("───────────────────────────────────────────────");

  if (launcher.installed) {
    if (dashboardOn) {
      log.raw(pc.bold("Next:") + ` type ${pc.cyan("delphi")} in any terminal to open the dashboard.`);
    } else {
      log.raw(pc.bold("Next:") + ` restart your AI tool — Delphi shows up as an MCP server.`);
      log.dim(`       (Type ${pc.cyan("delphi open")} later if you want the dashboard too.)`);
    }
    if (launcher.pathHint) log.dim(`  ${launcher.pathHint}`);
  } else if (chosenClients.length) {
    log.raw(`       Restart your AI tool — Delphi will appear as an MCP server.`);
  }
  log.dim("Lifecycle: `delphi status | logs | stop | start | open`");
  console.log();
}
