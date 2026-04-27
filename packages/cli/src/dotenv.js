import fs from "node:fs/promises";
import path from "node:path";

/**
 * Minimal, lossless .env reader/writer.
 *
 * Goals:
 *   - Round-trip a file: parse → write produces a byte-equal output for an
 *     unchanged map.
 *   - Preserve comments, blank lines, and key order (templates have logical
 *     grouping the user shouldn't have shuffled).
 *   - Preserve keys not in the new map (someone added EMBEDDING_BATCH_SIZE
 *     after install — we don't want to lose it on the next `delphi config`).
 *   - Append new keys at the end under a marker so they're easy to spot.
 *
 * Non-goals:
 *   - Multi-line / shell-style line continuation (`\\\n`). Not used by Delphi.
 *   - Variable interpolation (`${OTHER_VAR}`). Not used by Delphi.
 *   - The Pydantic backend reads `os.getenv(KEY)`, which has none of these
 *     features either, so the file format is intentionally simple.
 *
 * Quoting rules on write:
 *   - If the value contains whitespace, `#`, or any of `'"\\$` we wrap it in
 *     double quotes and backslash-escape `"` and `\\` inside.
 *   - Otherwise we write it bare. This matches Docker Compose's parser and
 *     keeps simple values readable.
 */

const APPENDED_HEADER = "# ---- Added by `delphi config` ----";

/**
 * Parse .env contents into ordered tokens + a key→value map.
 *
 * Returns:
 *   {
 *     tokens: Array<{ kind: 'comment'|'blank'|'kv', text: string, key?: string, value?: string, raw?: string }>,
 *     map:    Map<string, string>   // last assignment wins (matches docker compose)
 *   }
 *
 * `tokens` lets the writer reproduce the file byte-for-byte except for the
 * lines whose values changed.
 */
export function parseDotenv(text) {
  const lines = text.split(/\r?\n/);
  // The split above produces a trailing empty element for files that end in
  // a newline. We track that so we can re-emit it on write.
  const trailingNewline = lines.length > 0 && lines[lines.length - 1] === "";
  if (trailingNewline) lines.pop();

  const tokens = [];
  const map = new Map();

  for (const line of lines) {
    if (line.trim() === "") {
      tokens.push({ kind: "blank", text: line });
      continue;
    }
    if (line.trimStart().startsWith("#")) {
      tokens.push({ kind: "comment", text: line });
      continue;
    }
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m) {
      // Unrecognized line — keep as comment-equivalent so we don't lose it.
      tokens.push({ kind: "comment", text: line });
      continue;
    }
    const [, key, rawValue] = m;
    const value = unquote(rawValue);
    map.set(key, value);
    tokens.push({ kind: "kv", key, value, raw: line, text: line });
  }

  return { tokens, map, trailingNewline };
}

function unquote(raw) {
  const trimmed = raw.trim();
  if (trimmed.startsWith('"') && trimmed.endsWith('"') && trimmed.length >= 2) {
    return trimmed.slice(1, -1).replace(/\\(.)/g, "$1");
  }
  if (trimmed.startsWith("'") && trimmed.endsWith("'") && trimmed.length >= 2) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function quoteIfNeeded(value) {
  if (value === "") return "";
  if (/[\s#"'\\$]/.test(value)) {
    return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  }
  return value;
}

/**
 * Render a parsed file plus an updated map back to text. Updates land in
 * place; deletions remove the line; additions get appended.
 *
 * @param {object} parsed   — output of parseDotenv
 * @param {Map<string,string>|object} updates  — new map of key→value.
 *        Keys present here override the parsed map. To explicitly delete
 *        a key, set its value to `null` or `undefined`.
 */
export function renderDotenv(parsed, updates) {
  const updateMap = updates instanceof Map ? updates : new Map(Object.entries(updates));
  const seen = new Set();
  const out = [];

  for (const tok of parsed.tokens) {
    if (tok.kind !== "kv") {
      out.push(tok.text);
      continue;
    }
    if (updateMap.has(tok.key)) {
      const newVal = updateMap.get(tok.key);
      seen.add(tok.key);
      if (newVal === null || newVal === undefined) {
        // Drop the line entirely.
        continue;
      }
      out.push(`${tok.key}=${quoteIfNeeded(String(newVal))}`);
    } else {
      out.push(tok.text);
    }
  }

  // Anything in updateMap not yet emitted is a new key. Append under a
  // marker so a later eyeball-edit can find it.
  const additions = [];
  for (const [key, val] of updateMap) {
    if (seen.has(key)) continue;
    if (val === null || val === undefined) continue;
    additions.push(`${key}=${quoteIfNeeded(String(val))}`);
  }
  if (additions.length) {
    if (out.length && out[out.length - 1] !== "") out.push("");
    out.push(APPENDED_HEADER);
    for (const line of additions) out.push(line);
  }

  let result = out.join("\n");
  if (parsed.trailingNewline) result += "\n";
  return result;
}

/**
 * Read .env into { tokens, map }. Returns null if the file doesn't exist.
 */
export async function loadDotenv(filePath) {
  let text;
  try {
    text = await fs.readFile(filePath, "utf8");
  } catch (e) {
    if (e.code === "ENOENT") return null;
    throw e;
  }
  return parseDotenv(text);
}

/**
 * Atomically write a new .env. Strategy: write to .env.tmp in the same
 * directory, fsync it, then rename over .env. Crash anywhere in this
 * sequence leaves the original .env intact.
 *
 * Mode 0o600 — .env contains the JWT signing key and provider tokens.
 */
export async function writeDotenvAtomic(filePath, contents) {
  const dir = path.dirname(filePath);
  const tmp = path.join(dir, `.env.tmp.${process.pid}`);
  const fh = await fs.open(tmp, "w", 0o600);
  try {
    await fh.writeFile(contents, "utf8");
    await fh.sync();
  } finally {
    await fh.close();
  }
  await fs.rename(tmp, filePath);
  // rename preserves the dest's mode if dest exists, but ENOENT case set 0600.
  // Re-chmod defensively in case rename adopted umask-derived perms.
  await fs.chmod(filePath, 0o600);
}

/**
 * Convenience: load → apply updates → write.
 *
 * If the file doesn't exist and `template` is provided, parse the template
 * as the starting point. Used by the installer to seed `.env` from
 * `env.example` and survive future re-runs.
 */
export async function patchDotenv(filePath, updates, { template = null } = {}) {
  let parsed = await loadDotenv(filePath);
  if (!parsed) {
    if (template === null) {
      throw new Error(`${filePath} not found and no template provided.`);
    }
    parsed = parseDotenv(template);
    if (!parsed.trailingNewline) parsed.trailingNewline = true;
  }
  const text = renderDotenv(parsed, updates);
  await writeDotenvAtomic(filePath, text);
  return parsed;
}

/**
 * Compute a stable diff between two value maps. Used by `delphi config` to
 * print a summary before applying. Returns Array<{key, before, after}>.
 *
 * Secrets are flagged for masking by the caller — this helper just reports
 * what changed.
 */
export function diffEnv(beforeMap, afterMap) {
  const changes = [];
  const keys = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  for (const key of keys) {
    const before = beforeMap.get(key);
    const after = afterMap.get(key);
    if (before === after) continue;
    if (before === undefined && after === "") continue;
    if (after === undefined && before === "") continue;
    changes.push({ key, before, after });
  }
  return changes.sort((a, b) => a.key.localeCompare(b.key));
}
