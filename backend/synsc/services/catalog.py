"""Curated source catalog — name -> indexable source, for cold-start UX.

The biggest adoption blocker for a self-hosted context server is the cold start:
a fresh install knows nothing, so the user has to hunt down a GitHub URL and
index it before getting any value. Context7's whole moat is skipping that —
type a library name, get docs.

This catalog is Delphi's answer: a static, dependency-free map from common
library names (and aliases) to canonical, indexable sources. An agent can
``catalog_search("nextjs")`` and immediately ``quick_index`` the result without
the user knowing the repo URL. No network, no database — it's reference data.

Curated, not exhaustive: PRs welcome to extend ``CATALOG``.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    kind: str  # "repository" | "documentation"
    url: str
    description: str
    category: str
    aliases: tuple[str, ...] = ()
    ecosystem: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "url": self.url,
            "description": self.description,
            "category": self.category,
            "aliases": list(self.aliases),
            "ecosystem": self.ecosystem,
        }


def _e(name, url, description, category, aliases=(), ecosystem="", kind="repository"):
    return CatalogEntry(
        name=name, kind=kind, url=url, description=description,
        category=category, aliases=tuple(aliases), ecosystem=ecosystem,
    )


# A representative, curated set of popular sources across ecosystems. Repository
# entries point at GitHub (drivable by index_repository); doc entries point at
# documentation sites.
CATALOG: tuple[CatalogEntry, ...] = (
    # ── Frontend ──────────────────────────────────────────────────────────
    _e("react", "https://github.com/facebook/react", "Library for building user interfaces", "frontend", ("reactjs", "react.js"), "javascript"),
    _e("next.js", "https://github.com/vercel/next.js", "The React framework for production", "frontend", ("nextjs", "next"), "javascript"),
    _e("vue", "https://github.com/vuejs/core", "Progressive JavaScript framework", "frontend", ("vuejs", "vue.js", "vue3"), "javascript"),
    _e("svelte", "https://github.com/sveltejs/svelte", "Cybernetically enhanced web apps", "frontend", ("sveltejs",), "javascript"),
    _e("angular", "https://github.com/angular/angular", "Platform for building web applications", "frontend", ("angularjs",), "typescript"),
    _e("nuxt", "https://github.com/nuxt/nuxt", "The intuitive Vue framework", "frontend", ("nuxtjs",), "javascript"),
    _e("solid", "https://github.com/solidjs/solid", "Reactive UI library", "frontend", ("solidjs",), "javascript"),
    _e("tailwindcss", "https://github.com/tailwindlabs/tailwindcss", "Utility-first CSS framework", "frontend", ("tailwind",), "css"),
    _e("vite", "https://github.com/vitejs/vite", "Next generation frontend tooling", "frontend", (), "javascript"),
    _e("astro", "https://github.com/withastro/astro", "Web framework for content-driven sites", "frontend", (), "javascript"),
    _e("remix", "https://github.com/remix-run/remix", "Full stack web framework", "frontend", (), "javascript"),
    _e("redux", "https://github.com/reduxjs/redux", "Predictable state container for JS apps", "frontend", ("reduxjs",), "javascript"),
    _e("zustand", "https://github.com/pmndrs/zustand", "Bear necessities for state management", "frontend", (), "javascript"),
    _e("tanstack-query", "https://github.com/TanStack/query", "Powerful async state management", "frontend", ("react-query", "tanstack query"), "javascript"),
    # ── Backend / web ─────────────────────────────────────────────────────
    _e("express", "https://github.com/expressjs/express", "Fast, minimalist web framework for Node.js", "backend", ("expressjs",), "javascript"),
    _e("fastapi", "https://github.com/fastapi/fastapi", "Modern, fast web framework for Python APIs", "backend", (), "python"),
    _e("django", "https://github.com/django/django", "High-level Python web framework", "backend", (), "python"),
    _e("flask", "https://github.com/pallets/flask", "Lightweight WSGI web application framework", "backend", (), "python"),
    _e("rails", "https://github.com/rails/rails", "Ruby on Rails web framework", "backend", ("ruby on rails",), "ruby"),
    _e("nestjs", "https://github.com/nestjs/nest", "Progressive Node.js framework", "backend", ("nest",), "typescript"),
    _e("gin", "https://github.com/gin-gonic/gin", "HTTP web framework for Go", "backend", ("gin-gonic",), "go"),
    _e("fiber", "https://github.com/gofiber/fiber", "Express-inspired web framework for Go", "backend", (), "go"),
    _e("spring-boot", "https://github.com/spring-projects/spring-boot", "Java application framework", "backend", ("springboot", "spring"), "java"),
    _e("axum", "https://github.com/tokio-rs/axum", "Ergonomic web framework for Rust", "backend", (), "rust"),
    _e("actix-web", "https://github.com/actix/actix-web", "Powerful web framework for Rust", "backend", ("actix",), "rust"),
    _e("laravel", "https://github.com/laravel/laravel", "PHP web application framework", "backend", (), "php"),
    # ── Databases / data layer ────────────────────────────────────────────
    _e("postgres", "https://github.com/postgres/postgres", "Advanced open-source relational database", "database", ("postgresql",), "c"),
    _e("redis", "https://github.com/redis/redis", "In-memory data structure store", "database", (), "c"),
    _e("sqlite", "https://github.com/sqlite/sqlite", "Self-contained SQL database engine", "database", (), "c"),
    _e("mongodb", "https://github.com/mongodb/mongo", "Document-oriented NoSQL database", "database", ("mongo",), "cpp"),
    _e("duckdb", "https://github.com/duckdb/duckdb", "In-process analytical database", "database", (), "cpp"),
    _e("prisma", "https://github.com/prisma/prisma", "Next-generation Node.js & TypeScript ORM", "database", (), "typescript"),
    _e("sqlalchemy", "https://github.com/sqlalchemy/sqlalchemy", "Python SQL toolkit and ORM", "database", (), "python"),
    _e("pgvector", "https://github.com/pgvector/pgvector", "Vector similarity search for Postgres", "database", (), "c"),
    _e("drizzle", "https://github.com/drizzle-team/drizzle-orm", "TypeScript ORM", "database", ("drizzle-orm",), "typescript"),
    # ── AI / ML ───────────────────────────────────────────────────────────
    _e("pytorch", "https://github.com/pytorch/pytorch", "Tensors and dynamic neural networks", "ai-ml", ("torch",), "python"),
    _e("tensorflow", "https://github.com/tensorflow/tensorflow", "End-to-end ML platform", "ai-ml", ("tf",), "python"),
    _e("transformers", "https://github.com/huggingface/transformers", "State-of-the-art ML for PyTorch/TF/JAX", "ai-ml", ("huggingface transformers", "hf transformers"), "python"),
    _e("langchain", "https://github.com/langchain-ai/langchain", "Framework for LLM applications", "ai-ml", (), "python"),
    _e("llama-index", "https://github.com/run-llama/llama_index", "Data framework for LLM applications", "ai-ml", ("llamaindex",), "python"),
    _e("scikit-learn", "https://github.com/scikit-learn/scikit-learn", "Machine learning in Python", "ai-ml", ("sklearn",), "python"),
    _e("numpy", "https://github.com/numpy/numpy", "Fundamental package for scientific computing", "ai-ml", (), "python"),
    _e("pandas", "https://github.com/pandas-dev/pandas", "Powerful data analysis toolkit", "ai-ml", (), "python"),
    _e("jax", "https://github.com/google/jax", "Composable transformations of NumPy programs", "ai-ml", (), "python"),
    _e("vllm", "https://github.com/vllm-project/vllm", "High-throughput LLM inference engine", "ai-ml", (), "python"),
    _e("openai-python", "https://github.com/openai/openai-python", "Official OpenAI Python client", "ai-ml", ("openai python",), "python"),
    _e("ollama", "https://github.com/ollama/ollama", "Run large language models locally", "ai-ml", (), "go"),
    # ── DevOps / infra ────────────────────────────────────────────────────
    _e("kubernetes", "https://github.com/kubernetes/kubernetes", "Production-grade container orchestration", "devops", ("k8s",), "go"),
    _e("docker-cli", "https://github.com/docker/cli", "The Docker command line interface", "devops", ("docker",), "go"),
    _e("terraform", "https://github.com/hashicorp/terraform", "Infrastructure as code tool", "devops", (), "go"),
    _e("ansible", "https://github.com/ansible/ansible", "IT automation platform", "devops", (), "python"),
    _e("prometheus", "https://github.com/prometheus/prometheus", "Monitoring system and time series DB", "devops", (), "go"),
    _e("grafana", "https://github.com/grafana/grafana", "Observability and data visualization", "devops", (), "go"),
    # ── Languages / runtimes / stdlib ─────────────────────────────────────
    _e("cpython", "https://github.com/python/cpython", "The Python programming language", "language", ("python",), "python"),
    _e("node", "https://github.com/nodejs/node", "Node.js JavaScript runtime", "language", ("nodejs",), "javascript"),
    _e("typescript", "https://github.com/microsoft/TypeScript", "TypeScript language and compiler", "language", ("ts",), "typescript"),
    _e("go", "https://github.com/golang/go", "The Go programming language", "language", ("golang",), "go"),
    _e("rust", "https://github.com/rust-lang/rust", "The Rust programming language", "language", ("rustlang",), "rust"),
    _e("deno", "https://github.com/denoland/deno", "Secure runtime for JS and TS", "language", (), "rust"),
    _e("bun", "https://github.com/oven-sh/bun", "Fast all-in-one JavaScript runtime", "language", (), "zig"),
    # ── Testing / tooling ─────────────────────────────────────────────────
    _e("pytest", "https://github.com/pytest-dev/pytest", "Python testing framework", "tooling", (), "python"),
    _e("jest", "https://github.com/jestjs/jest", "Delightful JavaScript testing", "tooling", (), "javascript"),
    _e("playwright", "https://github.com/microsoft/playwright", "Web testing and automation", "tooling", (), "typescript"),
    _e("ruff", "https://github.com/astral-sh/ruff", "Extremely fast Python linter & formatter", "tooling", (), "rust"),
    _e("uv", "https://github.com/astral-sh/uv", "Fast Python package & project manager", "tooling", (), "rust"),
    _e("eslint", "https://github.com/eslint/eslint", "Pluggable JavaScript linter", "tooling", (), "javascript"),
    # ── Protocols / agents ────────────────────────────────────────────────
    _e("mcp", "https://github.com/modelcontextprotocol/modelcontextprotocol", "Model Context Protocol specification", "protocol", ("model context protocol", "model-context-protocol"), "typescript"),
    _e("mcp-python-sdk", "https://github.com/modelcontextprotocol/python-sdk", "Official MCP Python SDK", "protocol", ("mcp python",), "python"),
)


class CatalogService:
    """Search and resolve the curated source catalog."""

    def __init__(self, catalog: tuple[CatalogEntry, ...] = CATALOG) -> None:
        self.catalog = catalog

    def search(self, query: str, limit: int = 10, category: str | None = None) -> list[dict]:
        """Rank catalog entries against a free-text query."""
        q = (query or "").strip().lower()
        scored: list[tuple[float, CatalogEntry]] = []
        for entry in self.catalog:
            if category and entry.category != category:
                continue
            score = self._score(entry, q) if q else 0.5
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: (-x[0], x[1].name))
        return [e.to_dict() for _, e in scored[:limit]]

    def resolve(self, name: str) -> dict | None:
        """Resolve a library name to its single best catalog entry."""
        results = self.search(name, limit=1)
        return results[0] if results else None

    def list_entries(self, category: str | None = None) -> list[dict]:
        entries = [
            e for e in self.catalog if not category or e.category == category
        ]
        entries.sort(key=lambda e: (e.category, e.name))
        return [e.to_dict() for e in entries]

    def categories(self) -> list[str]:
        return sorted({e.category for e in self.catalog})

    @staticmethod
    def _score(entry: CatalogEntry, q: str) -> float:
        name = entry.name.lower()
        aliases = [a.lower() for a in entry.aliases]
        if q == name or q in aliases:
            return 100.0

        # Normalize separators so "next js" ~ "nextjs" ~ "next.js".
        def norm(s: str) -> str:
            return s.replace(".", "").replace("-", "").replace(" ", "")

        if norm(q) == norm(name) or norm(q) in {norm(a) for a in aliases}:
            return 95.0
        if name.startswith(q) or any(a.startswith(q) for a in aliases):
            return 70.0
        if q in name or any(q in a for a in aliases):
            return 50.0
        if q in entry.description.lower():
            return 20.0
        if q in entry.category or q in entry.ecosystem:
            return 10.0
        return 0.0
