"""Database connection management for Supabase PostgreSQL.

This module manages connections to Supabase's PostgreSQL database.
All data is stored in the cloud - no local SQLite support.
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
    """Get or create the PostgreSQL database engine.
    
    Configured for Supabase with connection pooling optimized for serverless.
    """
    global _engine
    if _engine is None:
        config = get_config()
        db_url = config.get_database_url()
        
        safe_url = make_url(db_url).render_as_string(hide_password=True)
        logger.info("Connecting to Supabase PostgreSQL", url=safe_url)
        
        # PostgreSQL configuration optimized for Supabase
        # pool_pre_ping disabled: adds ~1s latency per request (Supabase round-trip).
        # pool_recycle=1800 handles stale connections instead.
        _engine = create_engine(
            db_url,
            echo=config.database.echo,
            poolclass=QueuePool,
            pool_size=config.database.pool_size,
            max_overflow=config.database.max_overflow,
            pool_timeout=config.database.pool_timeout,
            pool_recycle=config.database.pool_recycle,
            pool_pre_ping=False,
            # Set a sane default statement timeout at the connection level.
            # Supabase's default can be too low (60-120s).  Individual
            # sessions can still override with SET LOCAL for long-running ops.
            #
            # TCP keepalives prevent Supabase/PgBouncer from killing long-lived
            # connections during extended indexing transactions (20+ minutes).
            # keepalives_idle=60: send first probe after 60s idle
            # keepalives_interval=15: probe every 15s after that
            # keepalives_count=4: give up after 4 missed probes (~2 min)
            connect_args={
                "options": "-c statement_timeout=120s -c idle_in_transaction_session_timeout=300s",
                "keepalives": 1,
                "keepalives_idle": 60,
                "keepalives_interval": 15,
                "keepalives_count": 4,
            },
        )
    
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get or create the session factory.
    
    OPTIMIZED: expire_on_commit=False avoids unnecessary DB roundtrips.
    """
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,  # Don't refresh objects after commit
        )
    return _SessionLocal


def init_db() -> None:
    """Initialize the database connection and verify setup.
    
    Verifies that:
    - Connection to Supabase PostgreSQL works
    - pgvector extension is enabled
    - Required tables exist
    - Local dev user exists (for development without auth)
    """
    from synsc.config import get_config
    config = get_config()
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
                    "Run supabase_setup.sql in your Supabase SQL editor first."
                )
            
            # Verify key tables exist (including user_repositories for deduplication)
            result = conn.execute(
                text("""
                    SELECT table_name FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name IN ('repositories', 'user_repositories', 'code_chunks', 'chunk_embeddings', 'api_keys')
                """)
            )
            tables = [row[0] for row in result.fetchall()]
            
            required_tables = ['repositories', 'user_repositories', 'code_chunks', 'chunk_embeddings', 'api_keys']
            missing = set(required_tables) - set(tables)
            
            if missing:
                raise RuntimeError(
                    f"Missing required tables: {missing}. "
                    f"Run supabase_setup.sql in your Supabase SQL editor first."
                )
            
            logger.info("Supabase database verified", tables=tables)
            
            # For local development without auth, ensure local dev user exists
            if not config.api.require_auth:
                _ensure_local_dev_user(conn)
                
    except Exception as e:
        logger.error("Failed to connect to Supabase database", error=str(e))
        raise


def _ensure_local_dev_user(conn) -> None:
    """Ensure the local development user exists in Supabase auth.users table.
    
    This user is used when running without authentication (local development).
    For local Supabase, we can insert directly into auth.users.
    """
    LOCAL_DEV_USER_ID = "00000000-0000-0000-0000-000000000001"
    
    # Check if local dev user exists in auth.users
    result = conn.execute(
        text("SELECT id FROM auth.users WHERE id = :user_id"),
        {"user_id": LOCAL_DEV_USER_ID}
    )
    
    if result.fetchone() is None:
        # Create local dev user in auth.users (Supabase's auth table)
        conn.execute(
            text("""
                INSERT INTO auth.users (
                    id, 
                    instance_id,
                    aud,
                    role,
                    email, 
                    encrypted_password,
                    email_confirmed_at,
                    created_at, 
                    updated_at,
                    confirmation_token,
                    recovery_token,
                    email_change_token_new,
                    email_change
                )
                VALUES (
                    :user_id,
                    '00000000-0000-0000-0000-000000000000',
                    'authenticated',
                    'authenticated',
                    'local@dev.local',
                    '',
                    NOW(),
                    NOW(), 
                    NOW(),
                    '',
                    '',
                    '',
                    ''
                )
                ON CONFLICT (id) DO NOTHING
            """),
            {"user_id": LOCAL_DEV_USER_ID}
        )
        conn.commit()
        logger.info("Created local development user in auth.users", user_id=LOCAL_DEV_USER_ID)


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
    """Check if we're using PostgreSQL - always True in this version."""
    return True
