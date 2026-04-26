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

export async function composeUp({ services = [], build = false, profiles = [] } = {}) {
  const args = [...profileFlags(profiles), "up", "-d"];
  if (build) args.push("--build");
  args.push(...services);
  const { code } = await compose(args);
  if (code !== 0) throw new Error(`docker compose up failed (exit ${code})`);
}

export async function composeDown({ removeVolumes = false, profiles = [] } = {}) {
  const args = [...profileFlags(profiles), "down"];
  if (removeVolumes) args.push("-v");
  const { code } = await compose(args);
  if (code !== 0) throw new Error(`docker compose down failed (exit ${code})`);
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
