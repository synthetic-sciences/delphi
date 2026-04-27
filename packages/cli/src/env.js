import fs from "node:fs/promises";
import crypto from "node:crypto";
import { ENV_FILE, ENV_TEMPLATE_FILE, STATE_FILE, ROOT } from "./paths.js";
import { loadDotenv, parseDotenv, renderDotenv, writeDotenvAtomic } from "./dotenv.js";

function randomHex(bytes) {
  return crypto.randomBytes(bytes).toString("hex");
}

/**
 * Embedding profiles. Each maps to env vars consumed by the backend.
 *
 *   kind: "local"  — sentence-transformers in-process. The model is pulled
 *                    from the HuggingFace Hub at first boot, then runs on
 *                    CPU/GPU inside the api container. HF_TOKEN is only
 *                    needed for gated models or higher Hub download rates.
 *   kind: "api"    — Gemini / OpenAI hosted embeddings; needs an API key.
 *
 * Backends targeting >768-dim outputs (Gemini, OpenAI) truncate at request
 * time. Local sentence-transformers does not truncate — pick a 768-dim
 * model (jina-v2-base-code, bge-base, mpnet) or set EMBEDDING_DIMENSION
 * yourself if you've migrated the pgvector schema.
 *
 * The HuggingFace Inference API (kind: "huggingface" in the backend) is
 * intentionally not exposed here — most users want the in-process path.
 * Power users can opt in by editing .env after install.
 */
export const EMBEDDING_PROFILES = {
  local_balanced: {
    label: "Local — sentence-transformers (any HuggingFace model, runs in-process, no API call)",
    kind: "local",
    available: true,
    promptModel: true,
    defaultModel: "jinaai/jina-embeddings-v2-base-code",
    modelHint: "any HF model id; pick a 768-dim one (jinaai/jina-embeddings-v2-base-code, BAAI/bge-base-en-v1.5, sentence-transformers/all-mpnet-base-v2)",
    optionalKeyEnvVar: "HF_TOKEN",
    optionalKeyHint: "https://huggingface.co/settings/tokens",
    optionalKeyReason: "only needed for gated/private models or higher Hub download rate limits",
    env: {
      EMBEDDING_PROVIDER: "local",
      EMBEDDING_DIMENSION: "768",
      EMBEDDING_DEVICE: "auto",
      EMBEDDING_BATCH_SIZE: "64",
    },
  },
  gemini: {
    label: "Google Gemini — gemini-embedding-001 (hosted, requires API key)",
    kind: "api",
    available: true,
    keyEnvVar: "GEMINI_API_KEY",
    keyHint: "https://aistudio.google.com/apikey",
    env: {
      EMBEDDING_PROVIDER: "gemini",
      EMBEDDING_MODEL: "gemini-embedding-001",
      EMBEDDING_DIMENSION: "768",
      EMBEDDING_BATCH_SIZE: "32",
    },
  },
  openai: {
    label: "OpenAI — text-embedding-3-small (hosted, requires API key)",
    kind: "api",
    available: true,
    keyEnvVar: "OPENAI_API_KEY",
    keyHint: "https://platform.openai.com/api-keys",
    env: {
      EMBEDDING_PROVIDER: "openai",
      EMBEDDING_MODEL: "text-embedding-3-small",
      EMBEDDING_DIMENSION: "768",
      EMBEDDING_BATCH_SIZE: "64",
    },
  },
};

/** Build the env-var map a profile + provider-config pair imply. The
 *  profile defaults provide non-secret tunables (DIMENSION, BATCH_SIZE,
 *  DEVICE) and the user-provided config layers on top — model overrides,
 *  API keys, etc. */
function buildProviderEnv(embeddingChoice, providerConfig) {
  const profile = EMBEDDING_PROFILES[embeddingChoice];
  if (!profile || !profile.available) {
    throw new Error(`Embedding profile ${embeddingChoice} is not available.`);
  }
  return { ...profile.env, ...providerConfig };
}

/** Auto-generated secrets the backend needs but the user never sees. */
function freshSecrets({ systemPassword } = {}) {
  return {
    serverSecret: randomHex(32),
    systemPassword: systemPassword || randomHex(16),
    postgresPassword: randomHex(16),
  };
}

/** Build the connection-string set + DB credentials together so they
 *  always match each other. */
function dbEnv(postgresPassword) {
  return {
    POSTGRES_USER: "synsc",
    POSTGRES_PASSWORD: postgresPassword,
    POSTGRES_DB: "synsc",
    DATABASE_URL: `postgresql://synsc:${postgresPassword}@postgres:5432/synsc`,
  };
}

/**
 * Generate the .env file for docker compose. Loads the slim env.example
 * template from the source clone and patches only the install-time keys,
 * so a re-install (or future `delphi config --rewrite`) preserves comments
 * and any user-added overrides.
 *
 * @param {object} opts
 * @param {string} opts.embeddingChoice
 * @param {object} [opts.providerConfig]
 * @param {string} [opts.systemPassword]
 */
export async function writeEnv({ embeddingChoice, providerConfig = {}, systemPassword }) {
  const secrets = freshSecrets({ systemPassword });
  const updates = {
    SERVER_SECRET: secrets.serverSecret,
    SYSTEM_PASSWORD: secrets.systemPassword,
    ...dbEnv(secrets.postgresPassword),
    ...buildProviderEnv(embeddingChoice, providerConfig),
  };

  // Read the template that ships in the source clone. If for some reason
  // it's missing, fall back to a minimal generated file so the installer
  // never hard-fails on a packaging glitch.
  let parsed;
  try {
    const text = await fs.readFile(ENV_TEMPLATE_FILE, "utf8");
    parsed = parseDotenv(text);
    if (!parsed.trailingNewline) parsed.trailingNewline = true;
  } catch {
    parsed = parseDotenv(
      "# Generated by @synsci/delphi installer (env.example missing).\n",
    );
  }

  const rendered = renderDotenv(parsed, updates);
  await writeDotenvAtomic(ENV_FILE, rendered);
  return secrets;
}

/**
 * Apply a partial config change to an existing .env. Used by `delphi config`
 * to rewrite only the keys the user actually changed; everything else
 * (comments, user-added vars, secrets) is preserved verbatim.
 *
 * Pass `null` for keys the caller wants to leave untouched. Pass `undefined`
 * (or omit) for keys the caller wants to delete from .env.
 *
 * Returns the updated map (post-write).
 */
export async function applyConfig(updates) {
  const parsed = await loadDotenv(ENV_FILE);
  if (!parsed) {
    throw new Error(
      `${ENV_FILE} not found. Run \`delphi init\` to create the install first.`,
    );
  }
  // Filter out null sentinels so renderDotenv doesn't drop them as deletes.
  const effective = {};
  for (const [k, v] of Object.entries(updates)) {
    if (v === null) continue;
    effective[k] = v;
  }
  const rendered = renderDotenv(parsed, effective);
  await writeDotenvAtomic(ENV_FILE, rendered);
  return parseDotenv(rendered).map;
}

export async function saveState(state) {
  await fs.mkdir(ROOT, { recursive: true });
  await fs.writeFile(STATE_FILE, JSON.stringify(state, null, 2), { mode: 0o600 });
}

export async function loadState() {
  try {
    const raw = await fs.readFile(STATE_FILE, "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
