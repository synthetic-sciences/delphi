"""
Unified SQLAlchemy database models for Synsc Context.

Models for:
- Code Repositories (with smart deduplication)
- Research Papers (with global deduplication)
- User associations and access control
- Code chunks, symbols, and paper chunks
- Citations, equations, code snippets from papers
- Job queue for async processing
"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Try to import pgvector for PostgreSQL
try:
    from pgvector.sqlalchemy import Vector
    PGVECTOR_AVAILABLE = True
except ImportError:
    PGVECTOR_AVAILABLE = False
    Vector = None  # type: ignore


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


def generate_uuid() -> str:
    """Generate a new UUID string."""
    return str(uuid4())


def utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


# ==============================================================================
# USER MODEL
# ==============================================================================


class User(Base):
    """User account — created via GitHub OAuth."""

    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_github_id", "github_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    email: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    github_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    github_username: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


# ==============================================================================
# CODE REPOSITORY MODELS
# ==============================================================================


class Repository(Base):
    """
    Repository model for storing GitHub repository metadata.
    
    DEDUPLICATION STRATEGY:
    - Repositories are globally unique by (url, branch)
    - is_public=True: Anyone can add to their collection and search
    - is_public=False: Only indexed_by user can access
    """

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("url", "branch", name="unique_repo_branch"),
        Index("idx_repositories_public", "is_public"),
        Index("idx_repositories_owner_name", "owner", "name"),
        Index("idx_repositories_indexed", "indexed_at"),
        Index("idx_repositories_indexed_by", "indexed_by"),
    )

    repo_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    
    url: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)
    
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    indexed_by: Mapped[str | None] = mapped_column(String(36), index=True)
    
    # Stats
    files_count: Mapped[int] = mapped_column(Integer, default=0)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0)
    symbols_count: Mapped[int] = mapped_column(Integer, default=0)
    total_lines: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    
    languages: Mapped[dict | None] = mapped_column(JSONB)
    local_path: Mapped[str | None] = mapped_column(Text)
    
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
    
    repo_metadata: Mapped[dict | None] = mapped_column(JSONB)

    # Diff-aware re-indexing metadata
    last_diff_stats: Mapped[dict | None] = mapped_column(JSONB)
    embedding_model: Mapped[str | None] = mapped_column(String(100))

    # Whether the repo was indexed with deep AST chunking
    deep_indexed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    files: Mapped[list["RepositoryFile"]] = relationship(
        "RepositoryFile", back_populates="repository", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        "CodeChunk", back_populates="repository", cascade="all, delete-orphan"
    )
    symbols: Mapped[list["Symbol"]] = relationship(
        "Symbol", back_populates="repository", cascade="all, delete-orphan"
    )
    user_links: Mapped[list["UserRepository"]] = relationship(
        "UserRepository", back_populates="repository", cascade="all, delete-orphan"
    )

    def get_languages(self) -> dict[str, float]:
        if not self.languages:
            return {}
        if isinstance(self.languages, dict):
            return self.languages
        return json.loads(self.languages)

    def set_languages(self, languages: dict[str, float]) -> None:
        self.languages = languages  # jsonb column

    def get_metadata(self) -> dict[str, Any]:
        if not self.repo_metadata:
            return {}
        if isinstance(self.repo_metadata, dict):
            return self.repo_metadata
        return json.loads(self.repo_metadata)

    def set_metadata(self, metadata: dict[str, Any]) -> None:
        self.repo_metadata = metadata  # jsonb column
    
    def can_user_access(self, user_id: str | None) -> bool:
        """Check if a user can see this repository based on visibility.

        Layer 1 (this method): checks is_public flag and indexed_by ownership.
        Layer 2 (query layer): search/list queries additionally enforce collection
        membership via user_repositories junction table join.

        For private repos, only the indexer has access.
        For public repos, this returns True — collection membership is enforced
        at the query layer (search_service, indexing_service list methods).
        """
        if self.is_public:
            return True
        if not user_id or not self.indexed_by:
            return False
        return str(self.indexed_by).lower() == str(user_id).lower()
    
    def can_user_delete(self, user_id: str | None) -> bool:
        if not user_id or not self.indexed_by:
            return False
        return str(self.indexed_by).lower() == str(user_id).lower()


class UserRepository(Base):
    """Junction table linking users to repositories."""

    __tablename__ = "user_repositories"
    __table_args__ = (
        UniqueConstraint("user_id", "repo_id", name="unique_user_repo"),
        Index("idx_user_repos_user", "user_id"),
        Index("idx_user_repos_repo", "repo_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repo_id"), nullable=False
    )
    
    nickname: Mapped[str | None] = mapped_column(String(255))
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    last_searched_at: Mapped[datetime | None] = mapped_column(DateTime)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_update: Mapped[bool] = mapped_column(Boolean, default=False)

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="user_links"
    )


class RepositoryFile(Base):
    """File within a repository."""

    __tablename__ = "repository_files"
    __table_args__ = (
        UniqueConstraint("repo_id", "file_path", name="unique_repo_file"),
        Index("idx_files_repo", "repo_id"),
        Index("idx_files_language", "language"),
    )

    file_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repo_id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str | None] = mapped_column(String(50))
    
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="files"
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        "CodeChunk", back_populates="file", cascade="all, delete-orphan"
    )
    symbols: Mapped[list["Symbol"]] = relationship(
        "Symbol", back_populates="file", cascade="all, delete-orphan"
    )


class CodeChunk(Base):
    """Code chunk for semantic search."""

    __tablename__ = "code_chunks"
    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index", name="unique_file_chunk"),
        Index("idx_chunks_repo", "repo_id"),
        Index("idx_chunks_file", "file_id"),
    )

    chunk_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repo_id"), nullable=False
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repository_files.file_id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    
    content: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    
    chunk_type: Mapped[str] = mapped_column(String(50), default="code")
    language: Mapped[str | None] = mapped_column(String(50))
    token_count: Mapped[int | None] = mapped_column(Integer)
    symbol_names: Mapped[str | None] = mapped_column(Text)  # JSON
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="chunks"
    )
    file: Mapped["RepositoryFile"] = relationship(
        "RepositoryFile", back_populates="chunks"
    )

    def get_symbol_names(self) -> list[str]:
        if not self.symbol_names:
            return []
        return json.loads(self.symbol_names)

    def set_symbol_names(self, names: list[str]) -> None:
        self.symbol_names = json.dumps(names)


class ChunkRelationship(Base):
    """Directed relationship between code chunks."""

    __tablename__ = "chunk_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_chunk_id", "target_chunk_id", "relationship_type",
            name="unique_chunk_relationship",
        ),
        Index("idx_chunk_rel_source", "source_chunk_id"),
        Index("idx_chunk_rel_target", "target_chunk_id"),
        Index("idx_chunk_rel_source_type", "source_chunk_id", "relationship_type"),
    )

    relationship_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    source_chunk_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("code_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_chunk_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("code_chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(20), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class Symbol(Base):
    """Code symbol (function, class, method, etc.)."""

    __tablename__ = "symbols"
    __table_args__ = (
        Index("idx_symbols_repo", "repo_id"),
        Index("idx_symbols_file", "file_id"),
        Index("idx_symbols_name", "name"),
        Index("idx_symbols_type", "symbol_type"),
        Index("idx_symbols_qualified", "qualified_name"),
    )

    symbol_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repo_id"), nullable=False
    )
    file_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repository_files.file_id"), nullable=False
    )
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    qualified_name: Mapped[str] = mapped_column(Text, nullable=False)
    symbol_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    signature: Mapped[str | None] = mapped_column(Text)
    docstring: Mapped[str | None] = mapped_column(Text)
    
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    
    is_exported: Mapped[bool] = mapped_column(Boolean, default=False)
    is_async: Mapped[bool] = mapped_column(Boolean, default=False)
    
    parent_symbol_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("symbols.symbol_id", ondelete="SET NULL")
    )
    
    parameters: Mapped[list | None] = mapped_column(JSONB)
    return_type: Mapped[str | None] = mapped_column(String(255))
    decorators: Mapped[list | None] = mapped_column(JSONB)
    
    language: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="symbols"
    )
    file: Mapped["RepositoryFile"] = relationship(
        "RepositoryFile", back_populates="symbols"
    )
    children: Mapped[list["Symbol"]] = relationship(
        "Symbol", back_populates="parent", remote_side=[symbol_id]
    )
    parent: Mapped["Symbol | None"] = relationship(
        "Symbol", back_populates="children", remote_side=[parent_symbol_id]
    )

    def get_parameters(self) -> list[dict[str, Any]]:
        if not self.parameters:
            return []
        if isinstance(self.parameters, list):
            return self.parameters
        return json.loads(self.parameters)

    def set_parameters(self, params: list[dict[str, Any]]) -> None:
        self.parameters = params  # jsonb column

    def get_decorators(self) -> list[str]:
        if not self.decorators:
            return []
        if isinstance(self.decorators, list):
            return self.decorators
        return json.loads(self.decorators)

    def set_decorators(self, decorators: list[str]) -> None:
        self.decorators = decorators  # jsonb column


# ==============================================================================
# RESEARCH PAPER MODELS
# ==============================================================================


class Paper(Base):
    """
    Paper model for storing research paper metadata.
    
    Papers are globally deduplicated by pdf_hash.
    """

    __tablename__ = "papers"
    __table_args__ = (
        Index("idx_papers_arxiv", "arxiv_id"),
        Index("idx_papers_hash", "pdf_hash"),
        Index("idx_papers_public", "is_public"),
        Index("idx_papers_indexed", "indexed_at"),
    )

    paper_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    arxiv_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list | None] = mapped_column(JSONB)
    abstract: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[str | None] = mapped_column(String(50))
    pdf_url: Mapped[str | None] = mapped_column(Text)
    pdf_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    indexed_by: Mapped[str | None] = mapped_column(String(36), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
    report: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    user_papers: Mapped[list["UserPaper"]] = relationship(
        "UserPaper", back_populates="paper", cascade="all, delete-orphan"
    )
    paper_chunks: Mapped[list["PaperChunk"]] = relationship(
        "PaperChunk", back_populates="paper", cascade="all, delete-orphan"
    )
    citations: Mapped[list["Citation"]] = relationship(
        "Citation", back_populates="paper", cascade="all, delete-orphan",
        foreign_keys="[Citation.paper_id]"
    )
    equations: Mapped[list["Equation"]] = relationship(
        "Equation", back_populates="paper", cascade="all, delete-orphan"
    )
    paper_code_snippets: Mapped[list["PaperCodeSnippet"]] = relationship(
        "PaperCodeSnippet", back_populates="paper", cascade="all, delete-orphan"
    )

    def get_authors(self) -> list[str]:
        if not self.authors:
            return []
        if isinstance(self.authors, list):
            return self.authors
        return json.loads(self.authors)

    def set_authors(self, authors: list[str]) -> None:
        self.authors = authors  # jsonb column accepts lists directly

    def get_metadata(self) -> dict[str, Any]:
        if not self.report:
            return {}
        if isinstance(self.report, dict):
            return self.report
        return json.loads(self.report)

    def set_metadata(self, metadata: dict[str, Any]) -> None:
        if isinstance(metadata, dict):
            self.report = metadata  # jsonb column accepts dicts directly
        else:
            self.report = json.dumps(metadata)


class UserPaper(Base):
    """Association table for users and papers."""

    __tablename__ = "user_papers"
    __table_args__ = (
        UniqueConstraint("user_id", "paper_id", name="unique_user_paper"),
        Index("idx_user_papers_user", "user_id"),
        Index("idx_user_papers_paper", "paper_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.paper_id"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    notes: Mapped[str | None] = mapped_column(Text)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)

    paper: Mapped["Paper"] = relationship("Paper", back_populates="user_papers")


class PaperChunk(Base):
    """Chunk model for paper text chunks."""

    __tablename__ = "paper_chunks"
    __table_args__ = (
        UniqueConstraint("paper_id", "chunk_index", name="unique_paper_chunk"),
        Index("idx_paper_chunks_paper", "paper_id"),
    )

    chunk_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.paper_id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    section_title: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(50), default="section")
    page_number: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    paper: Mapped["Paper"] = relationship("Paper", back_populates="paper_chunks")


class Citation(Base):
    """Citation extraction model."""

    __tablename__ = "citations"
    __table_args__ = (
        Index("idx_citations_paper", "paper_id"),
        Index("idx_citations_cited", "cited_paper_id"),
    )

    citation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.paper_id"), nullable=False
    )
    cited_paper_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("papers.paper_id")
    )
    citation_text: Mapped[str] = mapped_column(Text, nullable=False)
    citation_context: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    citation_number: Mapped[int | None] = mapped_column(Integer)
    external_reference: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    paper: Mapped["Paper"] = relationship(
        "Paper", back_populates="citations", foreign_keys=[paper_id]
    )
    cited_paper: Mapped["Paper | None"] = relationship(
        "Paper", foreign_keys=[cited_paper_id]
    )


class Equation(Base):
    """LaTeX equation extraction model."""

    __tablename__ = "equations"
    __table_args__ = (Index("idx_equations_paper", "paper_id"),)

    equation_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.paper_id"), nullable=False
    )
    equation_text: Mapped[str] = mapped_column(Text, nullable=False)
    equation_number: Mapped[str | None] = mapped_column(String(20))
    section_title: Mapped[str | None] = mapped_column(String(500))
    page_number: Mapped[int | None] = mapped_column(Integer)
    context: Mapped[str | None] = mapped_column(Text)
    equation_type: Mapped[str] = mapped_column(String(50), default="display")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    paper: Mapped["Paper"] = relationship("Paper", back_populates="equations")


class PaperCodeSnippet(Base):
    """Code snippet extraction from papers."""

    __tablename__ = "paper_code_snippets"
    __table_args__ = (Index("idx_paper_snippets_paper", "paper_id"),)

    snippet_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.paper_id"), nullable=False
    )
    code_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50))
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(500))
    listing_number: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)

    paper: Mapped["Paper"] = relationship("Paper", back_populates="paper_code_snippets")


# ==============================================================================
# GITHUB TOKEN MODEL
# ==============================================================================


class GitHubToken(Base):
    """Encrypted GitHub Personal Access Token for private repo cloning.

    One token per user. The token value is Fernet-encrypted at the application
    layer before storage and decrypted only in-memory at clone time.
    """

    __tablename__ = "github_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_label: Mapped[str | None] = mapped_column(String(255))
    github_username: Mapped[str | None] = mapped_column(String(255))
    github_id: Mapped[int | None] = mapped_column(Integer)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )


# ==============================================================================
# EMBEDDING MODELS (pgvector)
# ==============================================================================


class ChunkEmbedding(Base):
    """Code chunk embeddings stored in pgvector."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        Index("idx_embedding_chunk", "chunk_id"),
        Index("idx_embedding_repo", "repo_id"),
    )

    embedding_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("code_chunks.chunk_id", ondelete="CASCADE"), nullable=False, unique=True
    )
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.repo_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class PaperChunkEmbedding(Base):
    """Paper chunk embeddings stored in pgvector."""

    __tablename__ = "paper_chunk_embeddings"
    __table_args__ = (
        Index("idx_paper_embedding_chunk", "chunk_id"),
        Index("idx_paper_embedding_paper", "paper_id"),
    )

    embedding_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("paper_chunks.chunk_id"), nullable=False, unique=True
    )
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.paper_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


# ==============================================================================
# JOB QUEUE MODEL
# ==============================================================================


class IndexingJob(Base):
    """
    Job queue for asynchronous repository/paper indexing.
    
    Uses PostgreSQL as a simple but robust job queue.
    """
    
    __tablename__ = "indexing_jobs"
    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_user", "user_id"),
        Index("idx_jobs_created", "created_at"),
        Index("idx_jobs_priority_status", "priority", "status"),
    )
    
    job_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    
    # Job type: 'repository' or 'paper'
    job_type: Mapped[str] = mapped_column(String(20), default="repository")
    
    # For repos
    repo_url: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(String(255))
    
    # For papers
    paper_source: Mapped[str | None] = mapped_column(Text)  # arxiv URL/ID or file path
    
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    
    # Progress tracking
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(50))
    current_message: Mapped[str | None] = mapped_column(Text)
    
    # Stats
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_created: Mapped[int] = mapped_column(Integer, default=0)
    symbols_extracted: Mapped[int] = mapped_column(Integer, default=0)
    
    # Timing
    estimated_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    
    # Result
    result_repo_id: Mapped[str | None] = mapped_column(String(36))
    result_paper_id: Mapped[str | None] = mapped_column(String(36))
    error_message: Mapped[str | None] = mapped_column(Text)
    
    worker_id: Mapped[str | None] = mapped_column(String(50))
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now
    )
    
    def to_dict(self) -> dict:
        """Convert job to dictionary for API responses."""
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "job_type": self.job_type,
            "repo_url": self.repo_url,
            "branch": self.branch,
            "paper_source": self.paper_source,
            "status": self.status,
            "priority": self.priority,
            "progress": self.progress,
            "current_stage": self.current_stage,
            "current_message": self.current_message,
            "files_total": self.files_total,
            "files_processed": self.files_processed,
            "chunks_created": self.chunks_created,
            "symbols_extracted": self.symbols_extracted,
            "estimated_seconds": self.estimated_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_repo_id": self.result_repo_id,
            "result_paper_id": self.result_paper_id,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================


def get_vector_column_type(dimension: int = 768):
    """Get the appropriate vector column type based on available backend."""
    if PGVECTOR_AVAILABLE and Vector is not None:
        return Vector(dimension)
    return None
