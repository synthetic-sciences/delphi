import fs from "node:fs/promises";
import path from "node:path";
import { clientConfigPaths } from "./paths.js";
import { run, which } from "./system.js";
import { log } from "./log.js";

const SERVER_NAME = "synsci-delphi";

/** Build the MCP server entry that references the proxy package. */
export function buildServerEntry(apiKey, apiUrl) {
  return {
    command: "uvx",
    args: ["synsc-context-proxy"],
    env: {
      SYNSC_API_KEY: apiKey,
      SYNSC_API_URL: apiUrl,
    },
  };
}

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function readJsonOrEmpty(p) {
  try {
    const raw = await fs.readFile(p, "utf8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

async function writeJson(p, obj) {
  await fs.mkdir(path.dirname(p), { recursive: true });
  await fs.writeFile(p, JSON.stringify(obj, null, 2) + "\n");
}

/**
 * Detect which clients look installed. We don't require their config file to
 * exist — the user may be configuring a client they haven't launched yet —
 * but we surface what we find in the prompt.
 */
export async function detectInstalledClients() {
  const paths = clientConfigPaths();
  const detected = {
    claudeCode: await which("claude"),
    cursor: await exists(paths.cursor) || await exists(path.dirname(paths.cursor)),
    windsurf: await exists(paths.windsurf) || await exists(path.dirname(paths.windsurf)),
    claudeDesktop: await exists(paths.claudeDesktop) || await exists(path.dirname(paths.claudeDesktop)),
  };
  return detected;
}

/** Install via Claude Code's CLI command (the CLI manages the file location). */
async function installClaudeCode({ apiKey, apiUrl }) {
  const args = [
    "mcp", "add",
    "--scope", "user",
    "--transport", "stdio",
    "--env", `SYNSC_API_KEY=${apiKey}`,
    "--env", `SYNSC_API_URL=${apiUrl}`,
    SERVER_NAME,
    "--", "uvx", "synsc-context-proxy",
  ];
  const { code, stderr } = await run("claude", args, { silent: true });
  if (code !== 0) {
    throw new Error(`claude mcp add failed: ${stderr.trim()}`);
  }
}

/** Merge an mcpServers entry into a JSON config file. */
async function installViaJsonFile(filePath, entry, key = "mcpServers") {
  const cfg = await readJsonOrEmpty(filePath);
  cfg[key] = cfg[key] || {};
  cfg[key][SERVER_NAME] = entry;
  await writeJson(filePath, cfg);
}

/**
 * Install the Delphi MCP server in the requested clients. Returns a summary
 * keyed by client id with `{ ok, path?, error? }`.
 */
export async function installToClients(clientIds, { apiKey, apiUrl }) {
  const paths = clientConfigPaths();
  const entry = buildServerEntry(apiKey, apiUrl);
  const result = {};

  for (const id of clientIds) {
    try {
      if (id === "claudeCode") {
        await installClaudeCode({ apiKey, apiUrl });
        result[id] = { ok: true, path: "managed by `claude` CLI" };
      } else if (id === "cursor") {
        await installViaJsonFile(paths.cursor, entry);
        result[id] = { ok: true, path: paths.cursor };
      } else if (id === "windsurf") {
        await installViaJsonFile(paths.windsurf, entry);
        result[id] = { ok: true, path: paths.windsurf };
      } else if (id === "claudeDesktop") {
        await installViaJsonFile(paths.claudeDesktop, entry);
        result[id] = { ok: true, path: paths.claudeDesktop };
      } else {
        result[id] = { ok: false, error: `unknown client id: ${id}` };
      }
    } catch (e) {
      result[id] = { ok: false, error: e?.message || String(e) };
    }
  }
  return result;
}

export const CLIENT_LABELS = {
  claudeCode: "Claude Code (Anthropic CLI)",
  cursor: "Cursor",
  windsurf: "Windsurf",
  claudeDesktop: "Claude Desktop",
};
