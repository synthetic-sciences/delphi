import { log, spinner } from "./log.js";
import { composeUp } from "./docker.js";
import { loadState } from "./env.js";
import { waitForHealth } from "./health.js";

/**
 * Recreate api + worker so they pick up `.env` changes. Useful when a
 * power user has hand-edited `~/.synsci/delphi/source/.env` (e.g.
 * swapped a model id, added an advanced knob from docs/env-advanced.md)
 * and wants the change to take effect.
 *
 * IMPORTANT: this is `compose up --force-recreate`, NOT `compose
 * restart`. Docker Compose only re-reads `env_file` when a container is
 * *created*; `restart` reuses the original env from creation time. So a
 * plain restart silently keeps the old `.env` values, and the user
 * thinks reload didn't work. Force-recreate destroys the existing
 * container and creates a fresh one with the current env_file applied.
 *
 * Frontend isn't recreated — its build-time env (NEXT_PUBLIC_API_URL,
 * INTERNAL_API_URL) is baked into the image. Frontend changes require a
 * full re-init.
 *
 * @param {object} opts
 * @param {boolean} [opts.quiet]  Suppress the trailing "services reloaded"
 *   success line. Set when calling from another command (`delphi config`)
 *   that prints its own final status.
 */
export async function runReload({ quiet = false } = {}) {
  const state = await loadState();
  if (!state) {
    log.error("Delphi isn't installed yet. Run `npx @synsci/delphi init` first.");
    process.exit(1);
  }

  await spinner("recreating services (re-reads .env)", () =>
    composeUp({
      services: ["api", "worker"],
      profiles: state.profiles || [],
      withGpu: !!state.useGpu,
      forceRecreate: true,
      silent: true,
    }),
  );
  // recreate brings the containers back up, but the api takes a few
  // seconds to load the embedding model. Wait for /health before
  // declaring success — saves a confusing "config saved but nothing
  // happened" if the user runs another command right after.
  await spinner("waiting for API", () => waitForHealth());
  if (!quiet) log.success("services reloaded");
}
