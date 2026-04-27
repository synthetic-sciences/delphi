import os from "node:os";
import path from "node:path";

export const HOME = os.homedir();

/** Root for all Delphi-managed state on this machine. */
export const ROOT = process.env.SYNSCI_DELPHI_HOME || path.join(HOME, ".synsci", "delphi");

/** Where the cloned source lives. */
export const SOURCE_DIR = path.join(ROOT, "source");

/** Generated .env file consumed by docker compose. */
export const ENV_FILE = path.join(SOURCE_DIR, ".env");

/** Template file shipped in the source clone. The installer copies this to
 *  ENV_FILE on first run and patches only the install-time keys, so user
 *  edits + comments survive `delphi config` round-trips. */
export const ENV_TEMPLATE_FILE = path.join(SOURCE_DIR, "env.example");

/** Persisted state JSON written by `init` and read by other commands. */
export const STATE_FILE = path.join(ROOT, "state.json");

/** OS-aware MCP client config paths. */
export function clientConfigPaths() {
  const platform = process.platform;
  return {
    cursor: path.join(HOME, ".cursor", "mcp.json"),
    windsurf: path.join(HOME, ".codeium", "windsurf", "mcp_config.json"),
    claudeDesktop:
      platform === "darwin"
        ? path.join(HOME, "Library", "Application Support", "Claude", "claude_desktop_config.json")
        : platform === "win32"
        ? path.join(process.env.APPDATA || "", "Claude", "claude_desktop_config.json")
        : path.join(HOME, ".config", "Claude", "claude_desktop_config.json"),
  };
}
