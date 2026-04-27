import fs from "node:fs/promises";
import path from "node:path";
import { run } from "./system.js";
import { ROOT, SOURCE_DIR } from "./paths.js";
import { log } from "./log.js";

const REPO_URL = process.env.SYNSCI_DELPHI_REPO || "https://github.com/synthetic-sciences/delhpi.git";
// If unset, we let `git clone` use the remote's default branch (HEAD), which
// is more robust than hard-coding `main`/`master` since they differ per repo.
const REPO_REF = process.env.SYNSCI_DELPHI_REF || "";

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

/** Whether the configured REPO_URL points at a local checkout (file path or
 *  `file://` URL). Local clones don't benefit from `--depth 1` and git emits
 *  a noisy "warning: --depth is ignored in local clones" — skip the flag. */
function isLocalRepo(url) {
  return url.startsWith("file://") || url.startsWith("/") || url.startsWith("./") || url.startsWith("../");
}

/** Clone the Delphi repo into ~/.synsci/delphi/source, or hard-sync to the
 *  remote tip if it already exists. We use fetch + reset --hard rather than
 *  `pull --ff-only` because shallow clones can silently report "Already up
 *  to date" when in fact the local ref is just lagging — leaving the user
 *  on an older Dockerfile/source than they expect.
 *
 *  Returns `{ fresh, sha }` so callers can decide whether to surface the
 *  resolved commit to the user. All git invocations are silent — wrap this
 *  function in a spinner at the call site. */
export async function ensureSource() {
  await fs.mkdir(ROOT, { recursive: true });
  const isClone = await exists(path.join(SOURCE_DIR, ".git"));
  const local = isLocalRepo(REPO_URL);

  if (!isClone) {
    const args = ["clone"];
    if (!local) args.push("--depth", "1");
    if (REPO_REF) args.push("--branch", REPO_REF);
    args.push(REPO_URL, SOURCE_DIR);
    const { code, stderr } = await run("git", args, { silent: true });
    if (code !== 0) {
      throw new Error(`git clone failed (exit ${code})\n${stderr.trim()}`);
    }
  } else {
    const ref = REPO_REF || "HEAD";
    const fetchArgs = ["fetch"];
    if (!local) fetchArgs.push("--depth", "1");
    fetchArgs.push("origin", ref);
    let { code } = await run("git", fetchArgs, { cwd: SOURCE_DIR, silent: true });
    if (code !== 0) {
      // Network unavailable or remote went away — keep the existing checkout
      // rather than aborting the whole install.
      const { stdout: existingSha } = await run(
        "git", ["rev-parse", "--short", "HEAD"], { cwd: SOURCE_DIR, silent: true },
      );
      return { fresh: false, sha: existingSha.trim(), stale: true };
    }
    ({ code } = await run("git", ["reset", "--hard", "FETCH_HEAD"], { cwd: SOURCE_DIR, silent: true }));
    if (code !== 0) {
      const { stdout: existingSha } = await run(
        "git", ["rev-parse", "--short", "HEAD"], { cwd: SOURCE_DIR, silent: true },
      );
      return { fresh: false, sha: existingSha.trim(), stale: true };
    }
  }

  const { stdout } = await run(
    "git", ["rev-parse", "--short", "HEAD"], { cwd: SOURCE_DIR, silent: true },
  );
  return { fresh: !isClone, sha: stdout.trim(), stale: false };
}
