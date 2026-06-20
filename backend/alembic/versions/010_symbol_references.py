"""symbol_references (code-dependency graph)

Revision ID: 010_symbol_references
Revises: 009_docs_full_text
Create Date: 2026-06-20

Adds the ``symbol_references`` table — directed edges in the code-dependency
graph (``calls`` / ``imports``). This is the substrate for caller/callee lookup
and blast-radius / impact analysis ("what breaks if I change this function?").

Idempotent with respect to ``setup_local.sql``: uses CREATE TABLE / INDEX IF
NOT EXISTS so a DB bootstrapped from the SQL file is a no-op here.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "010_symbol_references"
down_revision: str | None = "009_docs_full_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS symbol_references (
            reference_id      VARCHAR(36) PRIMARY KEY,
            repo_id           VARCHAR(36) NOT NULL REFERENCES repositories(repo_id) ON DELETE CASCADE,
            source_symbol_id  VARCHAR(36) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
            target_symbol_id  VARCHAR(36) REFERENCES symbols(symbol_id) ON DELETE CASCADE,
            source_file_id    VARCHAR(36),
            callee_name       VARCHAR(255) NOT NULL,
            reference_type    VARCHAR(20) NOT NULL DEFAULT 'calls',
            line              INTEGER,
            is_resolved       BOOLEAN NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_symbol_reference_edge
                UNIQUE (source_symbol_id, target_symbol_id, callee_name, reference_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_symbol_refs_repo ON symbol_references (repo_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_symbol_refs_source ON symbol_references (source_symbol_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_symbol_refs_target ON symbol_references (target_symbol_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_symbol_refs_callee ON symbol_references (repo_id, callee_name)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS symbol_references")
