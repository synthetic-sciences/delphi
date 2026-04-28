/**
 * Plain-English error translation for the install / lifecycle commands.
 *
 * Every CLI command can throw a `RuntimeError`-shaped exception; the
 * underlying message often comes from docker, postgres, or python and
 * makes sense only to a developer who's seen it before. This module
 * turns the most common ones into a single short hint with a concrete
 * next step.
 *
 * Use:
 *   import { humanize } from "./error-hints.js";
 *   try { ... } catch (e) {
 *     const hint = humanize(e.message);
 *     if (hint) log.dim(`  ${hint}`);
 *     throw e;
 *   }
 *
 * Patterns are ordered from most-specific to most-general; the first
 * match wins.
 */

const PATTERNS = [
  // ─── Docker / Compose ─────────────────────────────────────────────

  {
    re: /address already in use|bind: port .+ is already allocated|ports are not available/i,
    hint: (m, msg) => {
      const portMatch = msg.match(/:(\d{2,5})\b/);
      const port = portMatch ? portMatch[1] : "the port";
      return (
        `Port ${port} is already used by another process on this machine. ` +
        `Find and stop it, then re-run:\n  ` +
        `lsof -i :${port}     # mac/linux: see what's holding it\n  ` +
        `kill <PID>           # stop it (note: kills your other dev server)`
      );
    },
  },
  {
    re: /Cannot connect to the Docker daemon|Is the docker daemon running/i,
    hint: () =>
      `Docker isn't running. Start Docker Desktop (mac/win) or run ` +
      `\`sudo systemctl start docker\` (linux), then re-run.`,
  },
  {
    re: /no space left on device|ENOSPC/i,
    hint: () =>
      `Disk is full. Image build needs ~15 GB free. Reclaim space:\n  ` +
      `docker system prune -a --volumes   # drops every unused image+volume\n  ` +
      `df -h                              # check what's actually free`,
  },

  // ─── Postgres / pgdata mismatch ──────────────────────────────────

  {
    re: /password authentication failed for user "synsc"/i,
    hint: () =>
      `Database password mismatch — usually from a half-completed prior install ` +
      `that left a stale pgdata volume. The fix:\n  ` +
      `delphi uninstall   # nukes containers + volumes; you'll lose any indexed data\n  ` +
      `npx @synsci/delphi   # fresh install, password regenerated against an empty volume`,
  },
  {
    re: /could not connect to server.*postgres/i,
    hint: () =>
      `API can't reach postgres. Check container state:\n  ` +
      `cd ~/.synsci/delphi/source && docker compose ps\n  ` +
      `docker compose logs postgres --tail 30`,
  },

  // ─── Embedding providers ─────────────────────────────────────────

  {
    re: /find_pruneable_heads_and_indices/,
    hint: () =>
      `The selected HuggingFace model uses a custom modeling file that ` +
      `imports a symbol removed in transformers 5.x (jina-v2-base-code is ` +
      `the common case). Switch to a standard-BERT model:\n  ` +
      `delphi config\n  ` +
      `# pick "Local", say "No" to current model, enter: BAAI/bge-base-en-v1.5`,
  },
  {
    re: /HuggingFace.*HTTP 401|HTTP 401.*HuggingFace|GatedRepoError/i,
    hint: () =>
      `HuggingFace rejected the request. If you're using a gated model ` +
      `(Llama, some Mistral), set HF_TOKEN via \`delphi config\`. Otherwise ` +
      `the model id may be private or wrong.`,
  },
  {
    re: /HuggingFace.*HTTP 429|rate limit/i,
    hint: () =>
      `HuggingFace rate-limited the download. Set HF_TOKEN via ` +
      `\`delphi config\` to raise the limit, or wait a few minutes and retry.`,
  },
  {
    re: /Gemini embeddings HTTP 401|API_KEY_INVALID/i,
    hint: () =>
      `Gemini API key was rejected. Check or regenerate at ` +
      `https://aistudio.google.com/apikey, then \`delphi config\` to update.`,
  },
  {
    re: /Gemini embeddings HTTP 429|RESOURCE_EXHAUSTED/i,
    hint: () =>
      `Gemini quota exhausted. Wait, switch keys, or move to a paid plan. ` +
      `Update via \`delphi config\` once you have a working key.`,
  },
  {
    re: /OpenAI embeddings HTTP 401/i,
    hint: () =>
      `OpenAI API key was rejected. Verify at ` +
      `https://platform.openai.com/api-keys, then \`delphi config\` to update.`,
  },
  {
    re: /OpenAI embeddings HTTP 429|insufficient_quota/i,
    hint: () =>
      `OpenAI quota exhausted or billing not set up. Check billing at ` +
      `https://platform.openai.com/account/billing, then retry.`,
  },

  // ─── CUDA / VRAM ─────────────────────────────────────────────────

  {
    re: /CUDA out of memory/i,
    hint: () =>
      `GPU ran out of VRAM. Either pick a smaller model (BAAI/bge-base-en-v1.5 ` +
      `fits a 4 GB card; Qwen3 needs 8+ GB) or fall back to CPU:\n  ` +
      `delphi config   # pick CPU only, or pick a smaller model`,
  },
  {
    re: /Expected one of cpu, cuda.*device.*auto/i,
    hint: () =>
      `EMBEDDING_DEVICE=auto was sent verbatim to torch which no longer ` +
      `accepts it. Update the CLI to 0.5.2+ or set EMBEDDING_DEVICE=cpu / ` +
      `cuda explicitly via \`delphi config\`.`,
  },

  // ─── Network ─────────────────────────────────────────────────────

  {
    re: /getaddrinfo ENOTFOUND|EAI_AGAIN|Could not resolve host/i,
    hint: () =>
      `DNS lookup failed. If you're behind a corporate VPN/proxy, set ` +
      `HTTP(S)_PROXY in your shell and retry. Otherwise check your network.`,
  },
  {
    re: /SSL certificate problem|unable to get local issuer certificate/i,
    hint: () =>
      `TLS verification failed — common with corporate SSL inspection. ` +
      `If you trust your network, set GIT_SSL_NO_VERIFY=true (git only) ` +
      `or install your org's CA in /etc/ssl/certs.`,
  },

  // ─── Filesystem perms ────────────────────────────────────────────

  {
    re: /PermissionError.*\.cache\/huggingface|Permission denied.*hf-cache/i,
    hint: () =>
      `HuggingFace cache directory has wrong owner. Fixed in 0.5.2 — ` +
      `update the CLI and rerun \`delphi uninstall && npx @synsci/delphi\`.`,
  },
];

export function humanize(message) {
  if (!message) return null;
  const text = String(message);
  for (const { re, hint } of PATTERNS) {
    const m = text.match(re);
    if (m) {
      try {
        return hint(m, text);
      } catch {
        return null;
      }
    }
  }
  return null;
}

/**
 * Print a friendly hint for an error to the console (does NOT swallow
 * the error; caller should re-throw or exit). Useful at the outer
 * boundary of every CLI command.
 */
export function printHint(log, error) {
  const hint = humanize(error?.message || String(error));
  if (!hint) return false;
  log.dim("");
  for (const line of hint.split("\n")) {
    log.dim(`  ${line}`);
  }
  return true;
}
