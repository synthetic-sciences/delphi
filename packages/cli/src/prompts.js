import { select, confirm, password, input } from "@inquirer/prompts";
import pc from "picocolors";
import { EMBEDDING_PROFILES } from "./env.js";

/**
 * Shared prompt builders used by both `delphi init` (first install) and
 * `delphi config` (post-install edits). Each prompt accepts `existing` so
 * the same code can either ask fresh or default to "keep current."
 */

function maskSecret(value) {
  if (!value) return "";
  if (value.length <= 4) return "••••";
  return `••••${value.slice(-4)}`;
}

/**
 * Render a profile's label, marking the user's current pick.
 */
function profileChoices({ current } = {}) {
  return Object.entries(EMBEDDING_PROFILES).map(([value, p]) => {
    const isCurrent = current && value === current;
    return {
      value,
      name: isCurrent ? `${p.label} ${pc.dim("(current)")}` : p.label,
      disabled: p.available ? false : pc.dim("(coming soon)"),
    };
  });
}

/**
 * @param {object} opts
 * @param {string} [opts.current]  EMBEDDING_PROFILES key already in use.
 *        When supplied the prompt defaults to it (Enter keeps the choice).
 */
export async function pickProvider({ current } = {}) {
  return select({
    message: "Which embeddings provider?",
    choices: profileChoices({ current }),
    default: current || "local_balanced",
  });
}

/**
 * Collect the provider-specific env vars: required key (Gemini/OpenAI),
 * optional HF_TOKEN (Local), and the model id (Local only).
 *
 * @param {object} profile  EMBEDDING_PROFILES[choice]
 * @param {object} opts
 * @param {Map<string,string>|object} [opts.existing]  current .env values.
 *        When the prompts find a value already set, we offer "keep current"
 *        instead of forcing a re-paste — important for swapping back-and-forth
 *        between providers without losing keys.
 */
export async function collectProviderConfig(profile, { existing = {} } = {}) {
  const get = (key) =>
    existing instanceof Map ? existing.get(key) : existing[key];

  const env = {};

  // Required key (Gemini / OpenAI).
  if (profile.keyEnvVar) {
    const current = get(profile.keyEnvVar);
    let collect = true;
    if (current) {
      const rotate = await confirm({
        message: `Rotate ${profile.keyEnvVar}? ${pc.dim("(current: " + maskSecret(current) + ")")}`,
        default: false,
      });
      if (!rotate) {
        env[profile.keyEnvVar] = current;
        collect = false;
      }
    }
    if (collect) {
      const key = await password({
        message: `Paste your ${profile.keyEnvVar}: ${pc.dim("(get one at " + profile.keyHint + ")")}`,
        mask: "•",
        validate: (v) => (v && v.trim().length > 8 ? true : "That doesn't look like a real key."),
      });
      env[profile.keyEnvVar] = key.trim();
    }
  }

  // Optional key (HF_TOKEN for Local). Empty input skips the var entirely.
  if (profile.optionalKeyEnvVar) {
    const current = get(profile.optionalKeyEnvVar);
    let collect = true;
    if (current) {
      const rotate = await confirm({
        message: `Rotate ${profile.optionalKeyEnvVar}? ${pc.dim("(current: " + maskSecret(current) + ")")}`,
        default: false,
      });
      if (!rotate) {
        env[profile.optionalKeyEnvVar] = current;
        collect = false;
      }
    }
    if (collect) {
      const key = await password({
        message:
          `${profile.optionalKeyEnvVar} ${pc.dim("(optional — " + profile.optionalKeyReason + "; get one at " + profile.optionalKeyHint + ")")}\n  ` +
          pc.dim("Press enter to skip"),
        mask: "•",
      });
      if (key.trim()) {
        env[profile.optionalKeyEnvVar] = key.trim();
      }
    }
  }

  // Model picker (Local only). We only treat the .env's existing
  // EMBEDDING_MODEL as "current" when the provider is unchanged — a
  // gemini-embedding-001 left over from a previous Gemini install is
  // meaningless to Local (which expects a HF org/repo id) and would
  // confuse the prompt's default suggestion.
  if (profile.promptModel) {
    const existingProvider = get("EMBEDDING_PROVIDER");
    const newProvider = profile.env?.EMBEDDING_PROVIDER;
    const providerUnchanged = existingProvider && existingProvider === newProvider;
    const currentModel = providerUnchanged
      ? get("EMBEDDING_MODEL") || profile.defaultModel
      : profile.defaultModel;

    const useCurrent = await confirm({
      message: `Use the current model? ${pc.dim("(" + currentModel + ")")}`,
      default: true,
    });
    if (useCurrent) {
      env.EMBEDDING_MODEL = currentModel;
    } else {
      const model = await input({
        message: `Enter the model id ${pc.dim("(" + profile.modelHint + ")")}`,
        validate: (v) =>
          v && v.trim().includes("/")
            ? true
            : "Use the form `org/repo` (e.g. BAAI/bge-base-en-v1.5).",
      });
      env.EMBEDDING_MODEL = model.trim();
    }
  } else if (profile.env && profile.env.EMBEDDING_MODEL) {
    // Provider has a fixed model — pin it explicitly so a previous Local
    // model id doesn't linger in .env after switching to Gemini/OpenAI.
    env.EMBEDDING_MODEL = profile.env.EMBEDDING_MODEL;
  }

  return env;
}

/**
 * Ask whether to use the detected GPU. Only relevant for the Local
 * (sentence-transformers) provider — Gemini / OpenAI run remote.
 *
 * @param {object} opts
 * @param {string} [opts.gpuName]  Display name of the detected GPU.
 * @param {string} [opts.current]  Current EMBEDDING_DEVICE in .env
 *        ("cuda", "cpu", "auto"). Used as the default when re-running
 *        from `delphi config`.
 *
 * Returns "cuda" or "cpu". Caller is responsible for translating that
 * into both EMBEDDING_DEVICE in .env and the docker-compose.gpu.yml
 * include flag (api container needs the GPU reservation to actually
 * see the device — without it sentence-transformers silently falls
 * back to CPU even when EMBEDDING_DEVICE=cuda).
 */
export async function pickDevice({ gpuName, current } = {}) {
  const choices = [
    {
      value: "cuda",
      name: `GPU (CUDA) ${pc.dim("— " + (gpuName || "detected NVIDIA GPU"))}${current === "cuda" ? pc.dim(" (current)") : ""}`,
    },
    {
      value: "cpu",
      name: `CPU only${current === "cpu" ? pc.dim(" (current)") : ""}`,
    },
  ];
  return select({
    message: "Run embeddings on:",
    choices,
    default: current === "cpu" ? "cpu" : "cuda",
  });
}

/**
 * Prompt for SYSTEM_PASSWORD. On install (`existing=null`) it's required.
 * On reconfig (`existing` truthy) it's gated by a `Change password?` confirm
 * so users don't have to retype on every `delphi config`.
 *
 * Returns `null` when the user opted to keep the existing password; the
 * caller should leave SYSTEM_PASSWORD untouched in .env.
 */
export async function promptSystemPassword({ existing = null } = {}) {
  if (existing) {
    const change = await confirm({
      message: "Change dashboard password?",
      default: false,
    });
    if (!change) return null;
  }
  const pw = await password({
    message: `Set a dashboard password ${pc.dim("(used to log in at http://localhost:3000 and to mint API keys)")}`,
    mask: "•",
    validate: (v) => (v && v.length >= 8 ? true : "At least 8 characters."),
  });
  return pw;
}
