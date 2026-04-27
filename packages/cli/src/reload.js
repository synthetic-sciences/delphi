import { log, spinner } from "./log.js";
import { composeRestart } from "./docker.js";
import { loadState } from "./env.js";
import { waitForHealth } from "./health.js";

/**
 * Restart api + worker so they pick up .env changes. Useful when a power
 * user has hand-edited `~/.synsci/delphi/source/.env` (e.g. added an
 * advanced knob from docs/env-advanced.md) and wants the change to take
 * effect without dropping volumes or rebuilding images.
 *
 * Frontend isn't restarted — its build-time env (NEXT_PUBLIC_API_URL,
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

  await spinner("restarting services", () =>
    composeRestart({ services: ["api", "worker"], silent: true, withGpu: !!state.useGpu }),
  );
  // restart returns immediately once the containers stop+start; the api
  // takes a few seconds to come back online. Wait for /health before
  // declaring success — saves a confusing "config saved but nothing
  // happened" if the user runs another command right after.
  await spinner("waiting for API", () => waitForHealth());
  if (!quiet) log.success("services reloaded");
}
