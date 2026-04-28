"""Configuration management for Delphi (synsc-context).

Local-only deployment - requires PostgreSQL + pgvector for storage.
Supports code repository, research paper, and dataset indexing.
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class EmbeddingConfig(BaseModel):
    """Configuration for embeddings (all local via sentence-transformers)."""

    model_name: str = Field(
        default="BAAI/bge-base-en-v1.5",
        description="Sentence-transformers model for all embeddings",
    )
    device: str = Field(
        default="cpu",
        description="Device for inference ('cpu', 'cuda', 'mps'). Auto-detects GPU.",
    )
    batch_size: int = Field(
        default=64, description="Batch size for embedding generation",
    )
    dimension: int = Field(
        default=768,
        description="Embedding dimension",
    )


class DatabaseConfig(BaseModel):
    """Configuration for database (PostgreSQL only)."""

    database_url: str = Field(
        default="",
        description="PostgreSQL connection string (set via DATABASE_URL env var)",
    )
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    user: str = Field(default="synsc", description="Database user")
    password: str = Field(default="", description="Database password")
    name: str = Field(default="synsc", description="Database name")
    echo: bool = Field(default=False, description="Echo SQL statements")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")
    pool_timeout: int = Field(default=30, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=1800, description="Recycle connections after N seconds")


class ChunkConfig(BaseModel):
    """Configuration for code chunking."""

    max_tokens: int = Field(default=2048, description="Max tokens per chunk")
    overlap_tokens: int = Field(default=100, description="Token overlap between chunks")
    min_chunk_tokens: int = Field(default=50, description="Minimum tokens for a chunk")
    respect_boundaries: bool = Field(
        default=True, description="Respect function/class boundaries when chunking"
    )


class StorageConfig(BaseModel):
    """Configuration for temporary file storage."""

    temp_dir: Path = Field(
        default=Path("/tmp/synsc-context"),
        description="Temporary directory for repo cloning and PDF processing",
    )
    keep_repos: bool = Field(
        default=False,
        description="Keep cloned repos after indexing (for debugging)",
    )

    def ensure_directories(self) -> None:
        """Create necessary directories."""
        self.temp_dir.mkdir(parents=True, exist_ok=True)


class GitConfig(BaseModel):
    """Configuration for Git operations."""

    clone_timeout: int = Field(default=300, description="Timeout for clone operations (seconds)")
    max_file_size_mb: int = Field(default=10, description="Max file size to index (MB)")
    max_repo_size_mb: int = Field(default=500, description="Max repository size (MB)")
    default_branch: str = Field(default="main", description="Default branch to clone")

    fast_mode: bool = Field(
        default=True,
        description="Skip test files, examples, and docs for faster indexing",
    )

    turbo_mode: bool = Field(
        default=True,
        description="Skip AST-based chunking for faster indexing (symbols still extracted)",
    )

    exclude_patterns: list[str] = Field(
        default=[
            "node_modules/", ".git/", "__pycache__/", ".venv/", "venv/",
            "dist/", "build/", ".next/", "target/", "out/", ".cache/",
            "coverage/", ".nyc_output/", ".pytest_cache/",
            "*.min.js", "*.min.css", "*.bundle.js", "*.chunk.js",
            "*.vendor.js", "*.vendors.js", "*.runtime.js",
            "*.generated.*", "*.gen.*", "*-generated.*", "*_generated.*",
            "*.g.dart", "*.g.go", "*.pb.go", "*_pb2.py",
            "*.map", "*.lock",
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "Cargo.lock", "poetry.lock", "Gemfile.lock", "composer.lock",
            "*.pyc", "*.pyo", "*.so", "*.dylib", "*.dll", "*.exe", "*.bin",
            "*.o", "*.a", "*.class", "*.jar", "*.war",
            "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.svg", "*.webp",
            "*.woff", "*.woff2", "*.ttf", "*.eot", "*.otf",
            "*.mp3", "*.mp4", "*.wav", "*.avi", "*.mov", "*.wmv",
            "*.pdf", "*.zip", "*.tar", "*.gz", "*.rar", "*.7z", "*.bz2",
            "*.db", "*.sqlite", "*.sqlite3",
            ".idea/", ".vscode/", "*.swp", "*.swo", "*~",
        ],
        description="Patterns to exclude from indexing",
    )

    fast_mode_skip_patterns: list[str] = Field(
        default=[
            "test/", "tests/", "__tests__/", "spec/", "specs/",
            "*_test.py", "*_test.js", "*_test.ts",
            "*.test.js", "*.test.ts", "*.test.tsx",
            "*.spec.js", "*.spec.ts", "*.spec.tsx",
            "test_*.py", "conftest.py",
            "fixtures/", "examples/", "example/",
            "*.txt",
            "benchmarks/", "benchmark/",
            "__mocks__/", "__snapshots__/",
            "e2e/", "cypress/", "playwright/",
            ".storybook/", "stories/",
        ],
        description="Additional patterns to skip in fast mode",
    )

    include_extensions: list[str] = Field(
        default=[
            ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs",
            ".ts", ".tsx", ".mts", ".cts", ".rs", ".go",
            ".java", ".kt", ".kts", ".swift",
            ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".cs",
            ".rb", ".php", ".scala", ".ex", ".exs",
            ".clj", ".cljs", ".cljc", ".hs", ".ml", ".mli",
            ".lua", ".r", ".R", ".jl",
            ".sh", ".bash", ".zsh", ".sql",
            ".graphql", ".gql", ".proto",
            ".yaml", ".yml", ".toml", ".json",
            ".css", ".scss", ".sass", ".less",
            ".html", ".htm", ".vue", ".svelte", ".astro",
            ".md", ".mdx", ".rst",
        ],
        description="File extensions to include",
    )


class PaperConfig(BaseModel):
    """Configuration for research paper processing."""

    max_pdf_size_mb: int = Field(default=50, description="Max PDF file size (MB)")
    chunk_size: int = Field(default=1000, description="Target chunk size in characters")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks")

    extract_citations: bool = Field(default=True, description="Extract citations from papers")
    extract_equations: bool = Field(default=True, description="Extract equations from papers")
    extract_code: bool = Field(default=True, description="Extract code snippets from papers")


class DatasetConfig(BaseModel):
    """Configuration for HuggingFace dataset processing."""

    chunk_size_tokens: int = Field(default=1024, description="Max tokens per dataset card chunk")
    chunk_overlap_tokens: int = Field(default=50, description="Token overlap between chunks")
    hf_token: str = Field(default="", description="Optional HuggingFace API token")


class ResearchConfig(BaseModel):
    """Configuration for the /v1/research endpoint."""

    provider: Literal["gemini", "anthropic"] = Field(
        default="gemini", description="LLM provider for research synthesis"
    )
    api_key: str = Field(default="", description="API key for the configured provider")
    model_quick: str = Field(default="gemini-2.5-flash")
    model_deep: str = Field(default="gemini-2.5-pro")
    quick_top_k: int = Field(default=10)
    deep_top_k: int = Field(default=25)
    deep_max_hops: int = Field(default=3)
    oracle_max_iterations: int = Field(default=5)
    quick_rpm: int = Field(default=10)
    deep_rpm: int = Field(default=3)
    oracle_rpm: int = Field(default=1)


class SearchConfig(BaseModel):
    """Configuration for search."""

    default_top_k: int = Field(default=10, description="Default number of search results")
    max_top_k: int = Field(default=100, description="Maximum number of search results")
    min_similarity_score: float = Field(
        default=0.3, description="Minimum similarity score for results"
    )
    enable_reranker: bool = Field(
        default=False, description="Enable cross-encoder reranking for improved search quality"
    )
    reranker_model: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Cross-encoder model for reranking",
    )
    reranker_blend_alpha: float = Field(
        default=0.4,
        description="Weight for cross-encoder score (0=vector only, 1=cross-encoder only)",
    )


class APIConfig(BaseModel):
    """Configuration for HTTP API server."""

    host: str = Field(default="0.0.0.0", description="Host to bind the server to")
    port: int = Field(default=8000, description="Port to bind the server to")
    require_auth: bool = Field(
        default=True,
        description="Require authentication (SYSTEM_PASSWORD for admin, API keys for agents)",
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins",
    )
    cors_methods: list[str] = Field(
        default=["GET", "POST", "DELETE", "PUT", "OPTIONS"],
        description="Allowed CORS methods",
    )
    cors_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-API-Key"],
        description="Allowed CORS headers",
    )


class FeatureFlags(BaseModel):
    """Feature flags for enabling/disabling functionality."""

    enable_code_indexing: bool = Field(default=True, description="Enable code repository indexing")
    enable_paper_indexing: bool = Field(default=True, description="Enable research paper indexing")
    enable_dataset_indexing: bool = Field(default=True, description="Enable HuggingFace dataset indexing")
    enable_job_queue: bool = Field(default=True, description="Enable background job queue")


class SynscConfig(BaseModel):
    """Main configuration for Delphi.

    Local-only deployment:
    - Database: PostgreSQL (local)
    - Vector Store: pgvector extension
    - Embeddings: sentence-transformers (local)
    """

    # Sub-configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    chunking: ChunkConfig = Field(default_factory=ChunkConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    features: FeatureFlags = Field(default_factory=FeatureFlags)

    # Server settings
    server_name: str = Field(default="synsc-context", description="MCP server name")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )

    @classmethod
    def from_env(cls) -> "SynscConfig":
        """Create configuration from environment variables."""
        config = cls()

        # Database — individual parts or full URL
        if db_host := os.getenv("POSTGRES_HOST"):
            config.database.host = db_host
        if db_port := os.getenv("POSTGRES_PORT"):
            config.database.port = int(db_port)
        if db_user := os.getenv("POSTGRES_USER"):
            config.database.user = db_user
        if db_password := os.getenv("POSTGRES_PASSWORD"):
            config.database.password = db_password
        if db_name := os.getenv("POSTGRES_DB"):
            config.database.name = db_name

        # DATABASE_URL takes precedence if set (overrides individual parts)
        if db_url := os.getenv("DATABASE_URL"):
            config.database.database_url = db_url

        # Embedding configuration
        if model := os.getenv("EMBEDDING_MODEL"):
            config.embeddings.model_name = model
        if device := os.getenv("EMBEDDING_DEVICE"):
            config.embeddings.device = device
        if batch_size := os.getenv("EMBEDDING_BATCH_SIZE"):
            config.embeddings.batch_size = int(batch_size)
        if dimension := os.getenv("EMBEDDING_DIMENSION"):
            config.embeddings.dimension = int(dimension)

        if log_level := os.getenv("SYNSC_LOG_LEVEL"):
            config.log_level = log_level  # type: ignore

        # API config
        if api_host := os.getenv("SYNSC_API_HOST"):
            config.api.host = api_host

        if api_port := os.getenv("SYNSC_API_PORT") or os.getenv("PORT"):
            config.api.port = int(api_port)

        if api_require_auth := os.getenv("SYNSC_REQUIRE_AUTH"):
            config.api.require_auth = api_require_auth.lower() in ("true", "1", "yes")

        # CORS origins (comma-separated)
        if cors := os.getenv("SYNSC_CORS_ORIGINS"):
            config.api.cors_origins = [o.strip() for o in cors.split(",") if o.strip()]
        if cors_methods := os.getenv("SYNSC_CORS_METHODS"):
            config.api.cors_methods = [m.strip() for m in cors_methods.split(",") if m.strip()]
        if cors_headers := os.getenv("SYNSC_CORS_HEADERS"):
            config.api.cors_headers = [h.strip() for h in cors_headers.split(",") if h.strip()]

        # Temp directory
        if temp_dir := os.getenv("SYNSC_TEMP_DIR"):
            config.storage.temp_dir = Path(temp_dir)

        # HuggingFace configuration
        if hf_token := os.getenv("HF_TOKEN"):
            config.dataset.hf_token = hf_token

        # Reranker
        if enable_reranker := os.getenv("SYNSC_ENABLE_RERANKER"):
            config.search.enable_reranker = enable_reranker.lower() in ("true", "1", "yes")
        if reranker_model := os.getenv("RERANKER_MODEL"):
            config.search.reranker_model = reranker_model
        if blend_alpha := os.getenv("RERANKER_BLEND_ALPHA"):
            config.search.reranker_blend_alpha = float(blend_alpha)

        # Research
        if research_provider := os.getenv("SYNSC_RESEARCH_PROVIDER"):
            config.research.provider = research_provider  # type: ignore
        if research_key := os.getenv("GEMINI_API_KEY") or os.getenv("SYNSC_RESEARCH_API_KEY"):
            config.research.api_key = research_key
        if model_quick := os.getenv("SYNSC_RESEARCH_MODEL_QUICK"):
            config.research.model_quick = model_quick
        if model_deep := os.getenv("SYNSC_RESEARCH_MODEL_DEEP"):
            config.research.model_deep = model_deep

        # Feature flags
        if enable_code := os.getenv("ENABLE_CODE_INDEXING"):
            config.features.enable_code_indexing = enable_code.lower() in ("true", "1", "yes")
        if enable_paper := os.getenv("ENABLE_PAPER_INDEXING"):
            config.features.enable_paper_indexing = enable_paper.lower() in ("true", "1", "yes")
        if enable_dataset := os.getenv("ENABLE_DATASET_INDEXING"):
            config.features.enable_dataset_indexing = enable_dataset.lower() in ("true", "1", "yes")

        return config

    def get_database_url(self) -> str:
        """Get the PostgreSQL database URL.

        Uses DATABASE_URL if set, otherwise builds from individual
        POSTGRES_* env vars.
        """
        if self.database.database_url:
            return self.database.database_url

        db = self.database
        if not db.password:
            raise ValueError(
                "Database password required. Set POSTGRES_PASSWORD or DATABASE_URL."
            )
        return f"postgresql://{db.user}:{db.password}@{db.host}:{db.port}/{db.name}"

    def initialize(self) -> None:
        """Initialize configuration and validate settings."""
        # Validate that we can build a database URL
        self.get_database_url()
        self.storage.ensure_directories()


# Global configuration instance
_config: SynscConfig | None = None


def get_config() -> SynscConfig:
    """Get global configuration instance."""
    global _config
    if _config is None:
        _config = SynscConfig.from_env()
        _config.initialize()
    return _config


def set_config(config: SynscConfig) -> None:
    """Set global configuration instance."""
    global _config
    _config = config
    _config.initialize()


# Aliases for backward compatibility
GitHubContextConfig = SynscConfig
