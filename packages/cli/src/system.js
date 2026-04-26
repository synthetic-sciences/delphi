import { spawn } from "node:child_process";

/**
 * Run a command and stream stdout/stderr to the parent process.
 * Returns the exit code.
 */
export function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: opts.silent ? "pipe" : "inherit",
      cwd: opts.cwd,
      env: { ...process.env, ...(opts.env || {}) },
    });
    let stdout = "";
    let stderr = "";
    if (opts.silent) {
      child.stdout?.on("data", (b) => (stdout += b.toString()));
      child.stderr?.on("data", (b) => (stderr += b.toString()));
    }
    child.on("error", reject);
    child.on("exit", (code) => resolve({ code: code ?? 1, stdout, stderr }));
  });
}

/** Check whether a binary is on PATH. */
export async function which(bin) {
  const cmd = process.platform === "win32" ? "where" : "which";
  const { code } = await run(cmd, [bin], { silent: true });
  return code === 0;
}

/** Strip CLI-plugin warnings (stale symlinks in ~/.docker/cli-plugins) so the
 *  user sees the actual error, not a wall of noise. */
function cleanDockerStderr(stderr) {
  return stderr
    .split("\n")
    .filter((line) => !/^WARNING: Plugin ".+" is not valid/.test(line))
    .filter((line) => !/^error: cannot exec ".+\/cli-plugins\/.+":/.test(line))
    .join("\n")
    .trim();
}

/** Check the Docker daemon is reachable, not just the binary. */
export async function dockerHealthy() {
  if (!(await which("docker"))) {
    return {
      ok: false,
      reason: "Docker isn't installed. Get Docker Desktop at https://www.docker.com/products/docker-desktop/",
    };
  }
  const { code, stderr } = await run("docker", ["info"], { silent: true });
  if (code === 0) return { ok: true };

  const cleaned = cleanDockerStderr(stderr);
  // The daemon-not-running message is verbose and unhelpful out of the box.
  // Detect it and replace with something actionable.
  if (/Cannot connect to the Docker daemon/i.test(cleaned) || /is the docker daemon running/i.test(cleaned)) {
    return {
      ok: false,
      reason: "Docker Desktop isn't running. Open it from Applications (or `open -a Docker`) and try again once the whale icon stops animating.",
    };
  }
  return { ok: false, reason: cleaned || "docker daemon not responding" };
}

/** Probe `docker compose` (v2) and fall back to `docker-compose` (v1). */
export async function dockerComposeCmd() {
  const { code: v2 } = await run("docker", ["compose", "version"], { silent: true });
  if (v2 === 0) return ["docker", ["compose"]];
  if (await which("docker-compose")) return ["docker-compose", []];
  return null;
}
