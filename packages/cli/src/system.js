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

/**
 * Find the path Docker uses for image / volume storage so we can
 * `df` against the right filesystem. Falls back to common defaults
 * if `docker info` doesn't surface it.
 */
async function dockerDataRoot() {
  const { code, stdout } = await run(
    "docker", ["info", "--format", "{{.DockerRootDir}}"], { silent: true },
  );
  if (code === 0 && stdout.trim()) return stdout.trim();
  return process.platform === "darwin" ? "/" : "/var/lib/docker";
}

/**
 * Pre-flight disk-space check. Image build needs ~12 GB (api ≈ 5 GB,
 * worker ≈ 5 GB, frontend ≈ 1 GB, base layers ≈ 1 GB) plus overhead
 * for the model cache and pgdata growth. We require 15 GB free as a
 * comfortable margin; warn at 25 GB free; below 8 GB we hard-fail
 * because the build will partway-OOM ENOSPC with a cryptic error.
 *
 * Returns `{ availGb, recommendedGb, ok, warn }`.
 */
export async function checkDiskSpace({
  recommendedGb = 25,
  hardFloorGb = 8,
} = {}) {
  const root = await dockerDataRoot();
  // -P forces POSIX format (consistent across mac BSD df + GNU df).
  // -k forces 1024-byte blocks so the parse is unambiguous.
  const { code, stdout } = await run("df", ["-Pk", root], { silent: true });
  if (code !== 0) {
    // df itself failed — don't block the install on a missing tool.
    return { availGb: null, recommendedGb, ok: true, warn: false };
  }
  const lines = stdout.trim().split("\n").filter(Boolean);
  const last = lines[lines.length - 1];
  const fields = last.split(/\s+/);
  // POSIX df row: Filesystem 1024-blocks Used Available Capacity Mounted
  const availKb = parseInt(fields[3], 10);
  if (!Number.isFinite(availKb)) {
    return { availGb: null, recommendedGb, ok: true, warn: false };
  }
  const availGb = availKb / (1024 * 1024);
  return {
    availGb,
    recommendedGb,
    ok: availGb >= hardFloorGb,
    warn: availGb < recommendedGb,
    root,
  };
}

/** Probe `docker compose` (v2) and fall back to `docker-compose` (v1). */
export async function dockerComposeCmd() {
  const { code: v2 } = await run("docker", ["compose", "version"], { silent: true });
  if (v2 === 0) return ["docker", ["compose"]];
  if (await which("docker-compose")) return ["docker-compose", []];
  return null;
}

/**
 * Best-effort install command for nvidia-container-toolkit on the
 * current Linux distro. Falls back to the upstream NVIDIA URL when we
 * can't recognize /etc/os-release. Used to give the user a copy-pasteable
 * fix when their host has a GPU but Docker isn't configured to pass it.
 */
async function linuxToolkitInstallHint() {
  const fs = await import("node:fs/promises");
  const text = await fs.readFile("/etc/os-release", "utf8").catch(() => "");
  if (/\bID=arch\b|\bID_LIKE=.*arch/i.test(text)) {
    return "yay -S nvidia-container-toolkit && sudo systemctl restart docker";
  }
  if (/\bID=(ubuntu|debian)\b|\bID_LIKE=.*debian/i.test(text)) {
    return "sudo apt install -y nvidia-container-toolkit && sudo systemctl restart docker";
  }
  if (/\bID=(fedora|rhel|centos|rocky|almalinux)\b/i.test(text)) {
    return "sudo dnf install -y nvidia-container-toolkit && sudo systemctl restart docker";
  }
  return "see https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html";
}

/**
 * Detect whether GPU acceleration is usable from inside a Docker
 * container on this host. Result shape:
 *
 *   { available: true,  gpu }                                  ← good to go
 *   { available: false, reason, hostGpu? }                     ← short-circuit
 *   { available: false, reason, hostGpu, installHint }         ← Linux-with-GPU,
 *       missing nvidia-container-toolkit; CLI surfaces the exact install
 *       command in the "we noticed your GPU, here's how to use it" warning.
 *
 * Platform-aware:
 *   - macOS:        Docker Desktop can't pass GPU to Linux containers
 *                   regardless of Apple Silicon / Intel. Bail immediately
 *                   so we don't waste time probing nvidia-smi (which won't
 *                   exist). Documented in docs/gpu.md.
 *   - Windows:      Same — Docker Desktop on Windows requires WSL2 + the
 *                   NVIDIA WSL toolkit. We treat it like Linux and let
 *                   the nvidia-smi / runtime probes decide.
 *   - Linux:        Run the full probe.
 */
export async function detectGpu() {
  if (process.platform === "darwin") {
    return {
      available: false,
      reason: "Docker on macOS can't pass GPU to containers (MPS unsupported)",
      platform: "darwin",
    };
  }

  // 1. Host-side: does the NVIDIA driver respond?
  if (!(await which("nvidia-smi"))) {
    return { available: false, reason: "nvidia-smi not on PATH" };
  }
  const { code: smiCode, stdout: smiOut } = await run("nvidia-smi", ["-L"], { silent: true });
  if (smiCode !== 0 || !smiOut.trim()) {
    return { available: false, reason: "nvidia-smi failed" };
  }
  const gpuName = (smiOut.split("\n")[0] || "").trim();

  // 2. Docker-side: can the runtime attach GPUs? `docker info` lists
  // configured runtimes — if `nvidia` is present the toolkit is in
  // place and the daemon is configured for pass-through.
  const { code: infoCode, stdout: info } = await run(
    "docker", ["info", "--format", "{{.Runtimes}}"], { silent: true },
  );
  if (infoCode !== 0) {
    return { available: false, reason: "docker info failed" };
  }
  if (!/\bnvidia\b/.test(info)) {
    const installHint = process.platform === "linux"
      ? await linuxToolkitInstallHint()
      : "see https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html";
    return {
      available: false,
      reason: "nvidia-container-toolkit not configured in Docker",
      hostGpu: gpuName,
      installHint,
    };
  }

  return { available: true, gpu: gpuName };
}
