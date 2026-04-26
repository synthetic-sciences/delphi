import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import { ROOT } from "./paths.js";

/**
 * Install a `delphi` launcher so the user can type `delphi` in any shell.
 *
 * Strategy:
 *   1. Write a wrapper script to ~/.synsci/delphi/bin/delphi that calls the
 *      currently-running CLI entry point (absolute node path).
 *   2. Try to symlink it to a directory likely on PATH:
 *      - /usr/local/bin (writable on Homebrew macOS without sudo)
 *      - ~/.local/bin (Linux convention)
 *   3. If neither is writable, return a `pathHint` telling the user how to
 *      add the bin dir to their PATH.
 *
 * Windows is handled by writing a .cmd file in ~/.synsci/delphi/bin and only
 * surfacing the path hint (no symlinking).
 */
export async function installLauncher() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const cliEntry = path.resolve(here, "..", "bin", "delphi.js");
  const binDir = path.join(ROOT, "bin");
  await fs.mkdir(binDir, { recursive: true });

  if (process.platform === "win32") {
    const cmdPath = path.join(binDir, "delphi.cmd");
    await fs.writeFile(
      cmdPath,
      `@echo off\r\nnode "${cliEntry}" %*\r\n`,
      { mode: 0o755 }
    );
    return {
      installed: true,
      shim: cmdPath,
      symlink: null,
      pathHint: `Add ${binDir} to your PATH (Windows). Then \`delphi\` works in any shell.`,
    };
  }

  const shimPath = path.join(binDir, "delphi");
  const node = process.execPath;
  const script = `#!/bin/sh
# @synsci/delphi launcher — installed by \`npx @synsci/delphi init\`.
# Tries the original CLI install; falls back to npx if it has been removed.
if [ -x "${node}" ] && [ -f "${cliEntry}" ]; then
  exec "${node}" "${cliEntry}" "$@"
else
  exec npx -y @synsci/delphi "$@"
fi
`;
  await fs.writeFile(shimPath, script, { mode: 0o755 });

  // Try to put it on PATH automatically.
  const candidates = ["/usr/local/bin/delphi", path.join(os.homedir(), ".local", "bin", "delphi")];
  let symlink = null;
  let lastErr = null;
  for (const target of candidates) {
    try {
      await fs.mkdir(path.dirname(target), { recursive: true });
      // Replace any pre-existing entry.
      try {
        await fs.unlink(target);
      } catch {}
      await fs.symlink(shimPath, target);
      symlink = target;
      break;
    } catch (e) {
      lastErr = e;
    }
  }

  if (symlink) {
    return { installed: true, shim: shimPath, symlink, pathHint: null };
  }
  return {
    installed: true,
    shim: shimPath,
    symlink: null,
    pathHint:
      `Couldn't symlink to /usr/local/bin or ~/.local/bin (${lastErr?.code || "permissions"}). ` +
      `Add this to your shell rc: ${`export PATH="${binDir}:$PATH"`}`,
  };
}
