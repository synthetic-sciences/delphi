import { select, checkbox, confirm } from "@inquirer/prompts";
import pc from "picocolors";
import { log, banner, spinner } from "./log.js";
import { dockerHealthy, which, detectGpu, checkDiskSpace } from "./system.js";
import { ensureSource } from "./source.js";
import { writeEnv, saveState, loadState, EMBEDDING_PROFILES } from "./env.js";
import { composePull, composeBuild, composeUp } from "./docker.js";
import { waitForHealth, bootstrap, apiBase } from "./health.js";
import {
  detectInstalledClients,
  installToClients,
  CLIENT_LABELS,
} from "./clients.js";
import { installLauncher } from "./launcher.js";
import { pickProvider, collectProviderConfig, pickDevice } from "./prompts.js";
import { discoverPorts } from "./ports.js";

const FLOWS = {
  agent: "Add to my coding agent (Claude Code, Cursor, Windsurf, Claude Desktop)",
  index: "Run my own index — pick a provider, attach an API key, get a dashboard",
};

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

  // Pre-flight runs BEFORE any setup prompt so a bad environment doesn't
  // wipe out provider/key/GPU input on retry. Reuse-path above returns
  // early without touching Docker, so it remains exempt. Docker health
  // uses `docker info`; port discovery uses a cheap TCP bind probe
  // (`lsof`/`ss` are best-effort holder lookup only, ENOENT falls back
  // silently — minimal distros without those tools still work).
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

  // Disk space — image build is ~12 GB plus model cache + pgdata
  // headroom. Catching ENOSPC here is much friendlier than letting
  // BuildKit fail mid-layer-export with a ~3-line cryptic error.
  const disk = await checkDiskSpace();
  if (disk.availGb !== null) {
    if (!disk.ok) {
      log.error(
        `Only ${disk.availGb.toFixed(1)} GB free at ${disk.root || "docker root"}. ` +
        `Image build needs at least 8 GB to complete; ${disk.recommendedGb} GB recommended.`,
      );
      log.dim("  Reclaim space and retry:");
      log.dim("    docker system prune -a --volumes");
      process.exit(1);
    } else if (disk.warn) {
      log.warn(
        `Only ${disk.availGb.toFixed(1)} GB free at ${disk.root || "docker root"} ` +
        `(${disk.recommendedGb} GB recommended). Build may complete but leave ` +
        `little headroom for the model cache.`,
      );
    } else {
      log.success(`disk: ${disk.availGb.toFixed(1)} GB free`);
    }
  }

  // Port collisions — scan all three host-side ports the install needs.
  // Frontend (3000) / postgres (5432) / api host port (8742) all fall
  // back to a higher port if their default is taken. We write the
  // chosen values to `.env` so:
  //   - docker-compose maps them via `${PORT:-default}` syntax
  //   - the frontend's `NEXT_PUBLIC_API_URL` build arg interpolates
  //     SYNSC_API_HOST_PORT, baking the correct localhost:port into
  //     the browser bundle for direct fetches that bypass server-side
  //     rewrites (file uploads, streaming endpoints).
  // The API port shift is the rare case (~1% of users), but when it
  // does fire the frontend rebuild that compose triggers picks up
  // the new URL automatically — no manual override needed.
  const ports = await discoverPorts();
  for (const p of [ports.frontend, ports.api, ports.postgres]) {
    if (p.requested === p.chosen) {
      log.success(`port ${p.requested} (${p.name}) free`);
    } else if (p.chosen) {
      log.warn(
        `port ${p.requested} held by ${p.holder || "another process"}; ` +
        `using ${pc.cyan(p.chosen)} for ${p.name} instead.`,
      );
    } else {
      log.error(
        `port ${p.requested} held by ${p.holder || "another process"} and ` +
        `no fallback available.`,
      );
      log.dim(`  Free up port ${p.requested} (e.g. 'lsof -i :${p.requested}' to find PID, then kill) and retry.`);
      process.exit(1);
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

  // ── GPU DETECTION ─────────────────────────────────────────────────────
  // Only relevant for the Local provider (Gemini / OpenAI run remote).
  // Detection touches `nvidia-smi` and `docker info` — both fast — so we
  // always probe but only surface a prompt when GPU is usable AND the
  // user picked Local. Result is persisted in state.json so subsequent
  // lifecycle commands re-apply the docker-compose.gpu.yml override.
  let useGpu = false;
  if (profile.kind === "local") {
    const gpu = await detectGpu();
    if (gpu.available) {
      const device = await pickDevice({ gpuName: gpu.gpu });
      useGpu = device === "cuda";
      providerConfig.EMBEDDING_DEVICE = device;
    } else if (gpu.hostGpu) {
      // Linux host has a GPU but Docker can't pass it. Surface the exact
      // install command for the user's distro so they don't have to
      // hunt — falling back to CPU otherwise.
      log.warn(`detected ${gpu.hostGpu} but Docker isn't configured to pass GPUs to containers.`);
      log.dim(`  Run:  ${gpu.installHint}`);
      log.dim("        then re-run init to enable GPU acceleration. Continuing on CPU.");
    } else if (gpu.platform === "darwin") {
      // Docker on macOS can't pass GPUs at all — flag once so users
      // don't expect MPS acceleration that the dockerized api can't
      // deliver. docs/gpu.md has the native-mode workaround.
      log.dim("  Note: Docker on macOS runs the api on CPU only. See docs/gpu.md for native MPS instructions.");
    }
  }

  // SYSTEM_PASSWORD is auto-generated. Magic-link auth signs the user
  // into the dashboard transparently via `delphi open`, and the CLI
  // mints API keys via /api/bootstrap on its own — the user never has
  // to type or remember a password. The auto-generated value still
  // lands in .env so power users can grab it for cross-device login or
  // change it later via `delphi config`.

  // Stash the discovered ports (scanned upfront in pre-flight) so writeEnv
  // persists them in .env.
  providerConfig.FRONTEND_PORT = String(ports.frontend.chosen);
  providerConfig.POSTGRES_PORT = String(ports.postgres.chosen);
  providerConfig.SYNSC_API_HOST_PORT = String(ports.api.chosen);

  // Source + .env
  const sourceInfo = await spinner("fetching source", () => ensureSource());
  if (sourceInfo.sha) {
    log.dim(`  source @ ${sourceInfo.sha}${sourceInfo.stale ? " (offline — using cached checkout)" : ""}`);
  }

  const secrets = await spinner("writing config", () =>
    writeEnv({ embeddingChoice, providerConfig }),
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
    composePull({ profiles, silent: true, withGpu: useGpu }),
  );
  await spinner("building images (api · worker" + (flow === "index" ? " · frontend" : "") + ")", () =>
    composeBuild({ profiles, silent: true, withGpu: useGpu }),
  );
  await spinner(
    useGpu ? "starting containers (with GPU reservation)" : "starting containers",
    () => composeUp({ build: false, profiles, silent: true, withGpu: useGpu }),
  );

  // Health
  await spinner("waiting for the API to come online", () => waitForHealth());

  // Pre-warm the embedding model. Without this, the user's first
  // index_repository or search call blocks for ~1-2 minutes while
  // sentence-transformers pulls Qwen3 (1.2 GB) or jina (440 MB) from
  // the Hub. Doing the download here means the container is fully
  // ready by the time the user triggers anything from Claude Code.
  // For hosted providers (Gemini / OpenAI) the probe validates the
  // API key end-to-end — failure surfaces immediately, not on first
  // search.
  try {
    const probeLabel =
      profile.kind === "local"
        ? "warming embedding model (downloads weights on first run, ~1-2 min)"
        : "verifying provider credentials";
    await spinner(probeLabel, async () => {
      const resp = await fetch(`${apiBase()}/backend-health?probe=embeddings`, {
        signal: AbortSignal.timeout(300_000),
      });
      const data = await resp.json();
      const callOk = data?.checks?.embedding_call?.ok;
      if (!callOk) {
        const err = data?.checks?.embedding_call?.error || "embedding probe failed";
        throw new Error(err);
      }
    });
  } catch (e) {
    // Non-fatal — install can continue; user can fix via `delphi config`.
    // The MCP wiring + dashboard are independent of the model being
    // ready, so we don't want a probe miss to roll back the whole install.
    log.warn(`embedding probe failed: ${e.message.slice(0, 200)}`);
    log.dim("  Install will continue. Run `delphi config` after fixing the underlying issue (bad API key, network, etc.).");
  }

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
      apiUrl: apiBase(),
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
    useGpu,
    embeddingChoice,
    apiKeyPreview: minted.key_preview,
    apiUrl: apiBase(),
    clients: Object.keys(installResults),
    launcher,
  });

  // Final report
  const dashboardOn = profiles.includes("dashboard");
  console.log();
  log.raw(pc.bold(pc.green("All set.")));
  log.dim("───────────────────────────────────────────────");
  if (dashboardOn) {
    const dashUrl = `http://localhost:${ports.frontend.chosen}`;
    log.raw(`  Dashboard:       ${pc.cyan(dashUrl)}  ${pc.dim("(auto-signs you in via `delphi open`)")}`);
  }
  log.raw(`  API:             ${pc.cyan(apiBase())}`);
  log.raw(`  API key:         ${pc.cyan(minted.api_key)}  ${pc.dim("(saved into MCP configs)")}`);
  // Always show. Even agent-flow users may run `delphi open` later;
  // they'll need the password if they ever log in from a different
  // device (phone, second laptop, no CLI to mint a magic link).
  const passwordHint = dashboardOn
    ? "(only needed for cross-device login; `delphi open` auto-signs you in here)"
    : "(stored in .env; only needed if you log into the dashboard from another device)";
  log.raw(`  Password:        ${pc.cyan(secrets.systemPassword)}  ${pc.dim(passwordHint)}`);
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
