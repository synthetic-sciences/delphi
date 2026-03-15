"""Configuration management for Synsc Context unified MCP server.

Supabase-only deployment - requires PostgreSQL + pgvector for storage.
Supports both code repository and research paper indexing.
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def _require_env(name: str) -> str:
    """Get a required environment variable or raise an error."""
    value = os.getenv(name)
    if not value:
        raise ValueError(
            f"Required environment variable {name} is not set. "
            f"Please configure Supabase credentials in your environment."
        )
    return value


class SupabaseConfig(BaseModel):
    """Configuration for Supabase integration (REQUIRED).
    
    Supabase API Key Naming Convention (2024+):
    - Publishable key (sb_publishable_xxx): Safe for client-side with RLS
    - Secret key (sb_secret_xxx): Server-side only, bypasses RLS
    
    Legacy names (anon_key, service_key) are supported for backward compatibility.
    """
    
    url: str = Field(
        default="",
        description="Supabase project URL (e.g., https://xxx.supabase.co)",
    )
    publishable_key: str = Field(
        default="",
        description="Supabase publishable key for client-side access (sb_publishable_xxx)",
    )
    secret_key: str = Field(
        default="",
        description="Supabase secret key for server-side operations (sb_secret_xxx)",
    )
    database_url: str = Field(
        default="",
        description="Direct PostgreSQL connection string (postgresql://...)",
    )
    
    @property
    def anon_key(self) -> str:
        """Legacy alias for publishable_key."""
        return self.publishable_key
    
    @anon_key.setter
    def anon_key(self, value: str) -> None:
        """Legacy setter for publishable_key."""
        self.publishable_key = value
    
    @property
    def service_key(self) -> str:
        """Legacy alias for secret_key."""
        return self.secret_key
    
    @service_key.setter
    def service_key(self, value: str) -> None:
        """Legacy setter for secret_key."""
        self.secret_key = value
    
    @property
    def is_configured(self) -> bool:
        """Check if Supabase is fully configured."""
        return bool(self.url and (self.secret_key or self.publishable_key) and self.database_url)
    
    @property
    def api_key(self) -> str:
        """Get the best available API key (secret key preferred for server-side)."""
        return self.secret_key or self.publishable_key
    
    def validate_configuration(self) -> None:
        """Validate that all required Supabase config is present."""
        if not self.url:
            raise ValueError("SUPABASE_URL is required")
        if not self.secret_key and not self.publishable_key:
            raise ValueError(
                "SUPABASE_SECRET_KEY (or legacy SUPABASE_SERVICE_KEY) or "
                "SUPABASE_PUBLISHABLE_KEY (or legacy SUPABASE_ANON_KEY) is required"
            )
        if not self.database_url:
            raise ValueError("SUPABASE_DATABASE_URL is required")
        if not self.database_url.startswith("postgresql"):
            raise ValueError("SUPABASE_DATABASE_URL must be a PostgreSQL connection string")


class TierSupabaseConfig(BaseModel):
    """External Supabase instance for tier management (OPTIONAL).

    This connects to a separate Supabase project that stores user tier data.
    If not configured, all users default to Free tier.
    """

    url: str = Field(default="", description="Tier Supabase project URL")
    secret_key: str = Field(default="", description="Tier Supabase secret key")

    @property
    def is_configured(self) -> bool:
        """Check if tier Supabase is configured."""
        return bool(self.url and self.secret_key)


class ChunkConfig(BaseModel):
    """Configuration for code chunking."""

    max_tokens: int = Field(default=2048, description="Max tokens per chunk")
    overlap_tokens: int = Field(default=100, description="Token overlap between chunks")
    min_chunk_tokens: int = Field(default=50, description="Minimum tokens for a chunk")
    respect_boundaries: bool = Field(
        default=True, description="Respect function/class boundaries when chunking"
    )


class EmbeddingConfig(BaseModel):
    """Configuration for embeddings.
    
    Two backends:
    - Gemini API: For code repository indexing (fast, API-based)
    - sentence-transformers: For research papers (local, no API key needed)
    """

    # Gemini settings (for code repos)
    gemini_model_name: str = Field(
        default="gemini-embedding-001",
        description="Gemini embedding model name",
    )
    gemini_api_key: str = Field(
        default="",
        description="Google AI API key for Gemini embeddings",
    )
    
    # Sentence-transformers settings (for papers)
    sentence_transformer_model: str = Field(
        default="all-mpnet-base-v2",
        description="Sentence-transformers model for paper embeddings",
    )
    paper_device: str = Field(
        default="cpu",
        description="Device for paper inference ('cpu', 'cuda', 'mps'). Auto-detects GPU.",
    )
    paper_batch_size: int = Field(
        default=32, description="Batch size for paper embedding generation",
    )
    
    # Common settings
    dimension: int = Field(
        default=768, 
        description="Embedding dimension (shared by both backends)"
    )
    batch_size: int = Field(
        default=100, description="Batch size for Gemini embedding generation"
    )


class DatabaseConfig(BaseModel):
    """Configuration for database (PostgreSQL only)."""

    echo: bool = Field(default=False, description="Echo SQL statements")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")
    pool_timeout: int = Field(default=30, description="Pool timeout in seconds")
    pool_recycle: int = Field(default=1800, description="Recycle connections after N seconds")


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
            # Directories
            "node_modules/", ".git/", "__pycache__/", ".venv/", "venv/",
            "dist/", "build/", ".next/", "target/", "out/", ".cache/",
            "coverage/", ".nyc_output/", ".pytest_cache/",

            # Minified/Bundled JavaScript/CSS
            "*.min.js", "*.min.css", "*.bundle.js", "*.chunk.js",
            "*.vendor.js", "*.vendors.js", "*.runtime.js",

            # Generated files
            "*.generated.*", "*.gen.*", "*-generated.*", "*_generated.*",
            "*.g.dart", "*.g.go", "*.pb.go", "*_pb2.py",

            # Source maps and lock files
            "*.map", "*.lock",
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
            "Cargo.lock", "poetry.lock", "Gemfile.lock", "composer.lock",

            # Compiled/Binary files
            "*.pyc", "*.pyo", "*.so", "*.dylib", "*.dll", "*.exe", "*.bin",
            "*.o", "*.a", "*.class", "*.jar", "*.war",

            # Media files
            "*.png", "*.jpg", "*.jpeg", "*.gif", "*.ico", "*.svg", "*.webp",
            "*.woff", "*.woff2", "*.ttf", "*.eot", "*.otf",
            "*.mp3", "*.mp4", "*.wav", "*.avi", "*.mov", "*.wmv",

            # Archives
            "*.pdf", "*.zip", "*.tar", "*.gz", "*.rar", "*.7z", "*.bz2",

            # Database files
            "*.db", "*.sqlite", "*.sqlite3",

            # IDE/Editor files
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
            # Documentation
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
    hf_token: str = Field(default="", description="Optional HuggingFace API token for higher rate limits")


class SearchConfig(BaseModel):
    """Configuration for search."""

    default_top_k: int = Field(default=10, description="Default number of search results")
    max_top_k: int = Field(default=100, description="Maximum number of search results")
    min_similarity_score: float = Field(
        default=0.3, description="Minimum similarity score for results"
    )


class APIConfig(BaseModel):
    """Configuration for HTTP API server."""

    host: str = Field(default="0.0.0.0", description="Host to bind the server to")
    port: int = Field(default=8000, description="Port to bind the server to")
    require_auth: bool = Field(
        default=True, description="Require API key authentication"
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins (set SYNSC_CORS_ORIGINS for production)",
    )
    rate_limit_per_minute: int = Field(
        default=60, description="Rate limit per API key per minute"
    )


class FeatureFlags(BaseModel):
    """Feature flags for enabling/disabling functionality."""
    
    enable_code_indexing: bool = Field(default=True, description="Enable code repository indexing")
    enable_paper_indexing: bool = Field(default=True, description="Enable research paper indexing")
    enable_dataset_indexing: bool = Field(default=True, description="Enable HuggingFace dataset indexing")
    enable_job_queue: bool = Field(default=True, description="Enable background job queue")


class SynscConfig(BaseModel):
    """Main configuration for Synsc Context unified MCP server.
    
    This is a Supabase-only deployment:
    - Database: PostgreSQL (via Supabase)
    - Vector Store: pgvector (Supabase extension)
    - Authentication: Supabase API keys
    """

    # Sub-configurations
    supabase: SupabaseConfig = Field(default_factory=SupabaseConfig)
    tier_supabase: TierSupabaseConfig = Field(default_factory=TierSupabaseConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    chunking: ChunkConfig = Field(default_factory=ChunkConfig)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    dataset: DatasetConfig = Field(default_factory=DatasetConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
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

        # Supabase configuration (REQUIRED)
        # Supports both new naming (secret/publishable) and legacy (service_role/anon)
        config.supabase.url = os.getenv("SUPABASE_URL", "")
        config.supabase.publishable_key = (
            os.getenv("SUPABASE_PUBLISHABLE_KEY") or 
            os.getenv("SUPABASE_ANON_KEY", "")
        )
        config.supabase.secret_key = (
            os.getenv("SUPABASE_SECRET_KEY") or 
            os.getenv("SUPABASE_SERVICE_ROLE_KEY") or  # Common typo/variation
            os.getenv("SUPABASE_SERVICE_KEY", "")
        )
        config.supabase.database_url = os.getenv("SUPABASE_DATABASE_URL", "")

        # Tier Supabase configuration (OPTIONAL - external tier management)
        config.tier_supabase.url = os.getenv("TIER_SUPABASE_URL", "")
        config.tier_supabase.secret_key = os.getenv("TIER_SUPABASE_SECRET_KEY", "")

        # Gemini API configuration (for code embeddings)
        if api_key := (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            config.embeddings.gemini_api_key = api_key

        # Paper embedding configuration (sentence-transformers)
        if paper_model := os.getenv("PAPER_EMBEDDING_MODEL"):
            config.embeddings.sentence_transformer_model = paper_model
        if paper_device := os.getenv("PAPER_EMBEDDING_DEVICE"):
            config.embeddings.paper_device = paper_device

        if log_level := os.getenv("SYNSC_LOG_LEVEL"):
            config.log_level = log_level  # type: ignore

        # API config
        if api_host := os.getenv("SYNSC_API_HOST"):
            config.api.host = api_host

        if api_port := os.getenv("SYNSC_API_PORT") or os.getenv("PORT"):
            config.api.port = int(api_port)

        if api_require_auth := os.getenv("SYNSC_REQUIRE_AUTH"):
            config.api.require_auth = api_require_auth.lower() in ("true", "1", "yes")
        
        # CORS origins (comma-separated, e.g. "https://app.synsc.dev,http://localhost:3000")
        if cors := os.getenv("SYNSC_CORS_ORIGINS"):
            config.api.cors_origins = [o.strip() for o in cors.split(",") if o.strip()]
        
        # Temp directory
        if temp_dir := os.getenv("SYNSC_TEMP_DIR"):
            config.storage.temp_dir = Path(temp_dir)
        
        # HuggingFace configuration
        if hf_token := os.getenv("HF_TOKEN"):
            config.dataset.hf_token = hf_token

        # Feature flags
        if enable_code := os.getenv("ENABLE_CODE_INDEXING"):
            config.features.enable_code_indexing = enable_code.lower() in ("true", "1", "yes")
        if enable_paper := os.getenv("ENABLE_PAPER_INDEXING"):
            config.features.enable_paper_indexing = enable_paper.lower() in ("true", "1", "yes")
        if enable_dataset := os.getenv("ENABLE_DATASET_INDEXING"):
            config.features.enable_dataset_indexing = enable_dataset.lower() in ("true", "1", "yes")

        return config
    
    def get_database_url(self) -> str:
        """Get the PostgreSQL database URL from Supabase config."""
        return self.supabase.database_url

    def initialize(self) -> None:
        """Initialize configuration and validate Supabase settings."""
        # Validate Supabase is configured
        self.supabase.validate_configuration()
        
        # Create temp directories
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
