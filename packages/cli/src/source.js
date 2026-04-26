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

/** Clone the Delphi repo into ~/.synsci/delphi/source, or hard-sync to the
 *  remote tip if it already exists. We use fetch + reset --hard rather than
 *  `pull --ff-only` because shallow clones can silently report "Already up
 *  to date" when in fact the local ref is just lagging — leaving the user
 *  on an older Dockerfile/source than they expect. */
export async function ensureSource() {
  await fs.mkdir(ROOT, { recursive: true });
  const isClone = await exists(path.join(SOURCE_DIR, ".git"));

  if (!isClone) {
    log.info(`cloning ${REPO_URL} → ${SOURCE_DIR}`);
    const args = ["clone", "--depth", "1"];
    if (REPO_REF) args.push("--branch", REPO_REF);
    args.push(REPO_URL, SOURCE_DIR);
    const { code } = await run("git", args);
    if (code !== 0) throw new Error(`git clone failed (exit ${code})`);
  } else {
    log.info(`updating source in ${SOURCE_DIR}`);
    const ref = REPO_REF || "HEAD";
    const fetchArgs = ["fetch", "--depth", "1", "origin", ref];
    let { code } = await run("git", fetchArgs, { cwd: SOURCE_DIR });
    if (code !== 0) {
      log.warn("git fetch failed — continuing with existing checkout");
      return { fresh: false };
    }
    ({ code } = await run("git", ["reset", "--hard", "FETCH_HEAD"], { cwd: SOURCE_DIR }));
    if (code !== 0) log.warn("git reset failed — continuing with existing checkout");
  }

  // Surface the resolved commit so users (and bug reports) can confirm what
  // was actually built, especially when a pull silently no-ops.
  const { stdout } = await run("git", ["rev-parse", "--short", "HEAD"], { cwd: SOURCE_DIR, silent: true });
  const sha = stdout.trim();
  if (sha) log.dim(`  source @ ${sha}`);

  return { fresh: !isClone };
}
