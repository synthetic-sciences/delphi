"""Database connection management for PostgreSQL.

This module manages connections to the local PostgreSQL database with pgvector.
"""

from contextlib import contextmanager
from typing import Generator

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from synsc.config import get_config

logger = structlog.get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Get or create the PostgreSQL database engine."""
    global _engine
    if _engine is None:
        config = get_config()
        db_url = config.get_database_url()

        safe_url = make_url(db_url).render_as_string(hide_password=True)
        logger.info("Connecting to PostgreSQL", url=safe_url)

        _engine = create_engine(
            db_url,
            echo=config.database.echo,
            poolclass=QueuePool,
            pool_size=config.database.pool_size,
            max_overflow=config.database.max_overflow,
            pool_timeout=config.database.pool_timeout,
            pool_recycle=config.database.pool_recycle,
            pool_pre_ping=True,
            connect_args={
                "options": "-c statement_timeout=120s -c idle_in_transaction_session_timeout=300s",
            },
        )

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get or create the session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def init_db() -> None:
    """Initialize the database connection and verify setup.

    Verifies that:
    - Connection to PostgreSQL works
    - pgvector extension is enabled
    - Required tables exist
    """
    engine = get_engine()

    try:
        with engine.connect() as conn:
            # Check if pgvector is available
            result = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            row = result.fetchone()
            if row:
                logger.info("PostgreSQL connected with pgvector extension")
            else:
                raise RuntimeError(
                    "pgvector extension not found! "
                    "Run setup_local.sql or use Docker Compose."
                )

            # Verify key tables exist
            result = conn.execute(
                text("""
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name IN ('users', 'api_keys', 'repositories', 'user_repositories', 'code_chunks', 'chunk_embeddings')
                """)
            )
            tables = [row[0] for row in result.fetchall()]

            required_tables = ['users', 'api_keys', 'repositories', 'user_repositories', 'code_chunks', 'chunk_embeddings']
            missing = set(required_tables) - set(tables)

            if missing:
                raise RuntimeError(
                    f"Missing required tables: {missing}. "
                    f"Run setup_local.sql or use Docker Compose."
                )

            logger.info("Database verified", tables=tables)

    except Exception as e:
        logger.error("Failed to connect to database", error=str(e))
        raise


def reset_engine() -> None:
    """Reset the database engine (useful for testing or reconfiguration)."""
    global _engine, _SessionLocal

    if _engine is not None:
        _engine.dispose()
        _engine = None
    _SessionLocal = None

    logger.info("Database engine reset")


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Get a database session with automatic cleanup."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Session:
    """Get a new database session (caller responsible for cleanup)."""
    SessionLocal = get_session_factory()
    return SessionLocal()


def is_using_postgres() -> bool:
    """Check if we're using PostgreSQL - always True."""
    return True
