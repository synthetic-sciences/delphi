# Lite deployment — the smallest useful Delphi

The default stack downloads a ~1.2 GB embedding model and runs Postgres, an API,
a worker, and (optionally) a dashboard. That's the right setup for a team index.
For a solo dev, a laptop, CI, or an air-gapped box, it's more than you need.

The **lite profile** strips it to the essentials: Postgres + API, no model
download, boots in seconds.

```bash
docker compose -f docker-compose.lite.yml up --build
# API on http://localhost:8742
```

## What "lite" changes

| | Full stack | Lite stack |
|---|---|---|
| Services | postgres + api + worker + frontend | postgres + api |
| Embeddings | sentence-transformers (~1.2 GB download) | `hash` provider — **no download** |
| Reranker | optional cross-encoder | off |
| Indexing | async via worker | synchronous via the API |
| Cold boot | model load (GB of RAM) | seconds, low RAM |

## How it stays useful without a real embedding model

Setting `EMBEDDING_PROVIDER=hash` swaps the neural embedder for a deterministic
**feature-hashing vectorizer** (`backend/synsc/embeddings/providers.py`). It
needs no model and no network, and it produces a 768-dim unit vector whose
cosine similarity reflects shared-token overlap.

Crucially, Delphi's retrieval is **hybrid** — vector + BM25 + exact-symbol +
exact-path + trigram. The lexical and symbol branches don't depend on the neural
model at all, and the benchmark (`bench/`) shows they already carry most of the
quality (BM25 recall@5 ≈ 0.92; symbol retrieval is the most precise and
token-efficient). The hash vector adds a cheap lexical-overlap signal on top.

What you give up: true **semantic** recall (matching intent when the words
differ — "auth" finding "login"). When you want that, flip the provider back:

```bash
EMBEDDING_PROVIDER=local docker compose -f docker-compose.lite.yml up --build
# or wire up a hosted embedder:
EMBEDDING_PROVIDER=gemini GEMINI_API_KEY=... docker compose -f docker-compose.lite.yml up
```

## Running the API without Docker at all

Lite mode also makes a no-Docker run practical, since there's no model to fetch:

```bash
cd backend
uv sync
EMBEDDING_PROVIDER=hash DATABASE_URL=postgresql://... uv run synsc-context-http
```

You still need a Postgres with the `vector` extension; everything else is in the
single API process.
