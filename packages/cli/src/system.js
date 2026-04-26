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

/** Check the Docker daemon is reachable, not just the binary. */
export async function dockerHealthy() {
  if (!(await which("docker"))) return { ok: false, reason: "docker binary not found on PATH" };
  const { code, stderr } = await run("docker", ["info"], { silent: true });
  if (code !== 0) return { ok: false, reason: stderr.trim() || "docker daemon not responding" };
  return { ok: true };
}

/** Probe `docker compose` (v2) and fall back to `docker-compose` (v1). */
export async function dockerComposeCmd() {
  const { code: v2 } = await run("docker", ["compose", "version"], { silent: true });
  if (v2 === 0) return ["docker", ["compose"]];
  if (await which("docker-compose")) return ["docker-compose", []];
  return null;
}
