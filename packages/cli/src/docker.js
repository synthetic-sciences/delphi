import { run, dockerComposeCmd } from "./system.js";
import { SOURCE_DIR } from "./paths.js";

async function compose(args, opts = {}) {
  const tool = await dockerComposeCmd();
  if (!tool) throw new Error("Docker Compose not found. Install Docker Desktop or `docker compose` plugin.");
  const [bin, prefix] = tool;
  return run(bin, [...prefix, ...args], { cwd: SOURCE_DIR, ...opts });
}

function profileFlags(profiles = []) {
  const out = [];
  for (const p of profiles) out.push("--profile", p);
  return out;
}

export async function composeUp({ services = [], build = false, profiles = [], silent = false } = {}) {
  const args = [...profileFlags(profiles), "up", "-d"];
  if (build) args.push("--build");
  args.push(...services);
  // When silent, swallow the BuildKit / progress noise so the launcher can
  // wrap the call in a spinner. On failure, surface stderr so the user has
  // something actionable instead of a bare "exit 1".
  const { code, stderr } = await compose(args, { silent });
  if (code !== 0) {
    const detail = silent && stderr ? `\n${stderr.trim()}` : "";
    throw new Error(`docker compose up failed (exit ${code})${detail}`);
  }
}

/** Pull base images for the selected profiles. Phase 1 of a fresh start —
 *  the network-bound step that's slow on first run. */
export async function composePull({ profiles = [], silent = false } = {}) {
  const args = [...profileFlags(profiles), "pull"];
  const { code, stderr } = await compose(args, { silent });
  if (code !== 0) {
    const detail = silent && stderr ? `\n${stderr.trim()}` : "";
    throw new Error(`docker compose pull failed (exit ${code})${detail}`);
  }
}

/** Build local images. Phase 2 — CPU-bound, mostly cached after first run. */
export async function composeBuild({ profiles = [], silent = false } = {}) {
  const args = [...profileFlags(profiles), "build"];
  const { code, stderr } = await compose(args, { silent });
  if (code !== 0) {
    const detail = silent && stderr ? `\n${stderr.trim()}` : "";
    throw new Error(`docker compose build failed (exit ${code})${detail}`);
  }
}

/** Restart specific services (or all of them when `services` is empty).
 *  Used by `delphi reload` and `delphi config` to pick up .env changes
 *  without doing a full down → up cycle (which would also drop volumes
 *  if you forgot the right flags). */
export async function composeRestart({ services = [], profiles = [], silent = false } = {}) {
  const args = [...profileFlags(profiles), "restart", ...services];
  const { code, stderr } = await compose(args, { silent });
  if (code !== 0) {
    const detail = silent && stderr ? `\n${stderr.trim()}` : "";
    throw new Error(`docker compose restart failed (exit ${code})${detail}`);
  }
}

export async function composeDown({ removeVolumes = false, profiles = [], silent = false } = {}) {
  const args = [...profileFlags(profiles), "down"];
  if (removeVolumes) args.push("-v");
  const { code, stderr } = await compose(args, { silent });
  if (code !== 0) {
    const detail = silent && stderr ? `\n${stderr.trim()}` : "";
    throw new Error(`docker compose down failed (exit ${code})${detail}`);
  }
}

export async function composeStatus({ profiles = [] } = {}) {
  const { code, stdout } = await compose(
    [...profileFlags(profiles), "ps", "--format", "json"],
    { silent: true }
  );
  if (code !== 0) return [];
  return stdout
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

export async function composeLogs({ follow = false, services = [], profiles = [] } = {}) {
  const args = [...profileFlags(profiles), "logs"];
  if (follow) args.push("-f");
  args.push("--tail", "200", ...services);
  await compose(args);
}
