"""doc_versions

Revision ID: 007_doc_versions
Revises: 006_context_blobs
Create Date: 2026-05-17

Adds a ``version`` column to documentation_sources so agents can pin doc
retrieval to a specific release (Context7 parity:
``/org/repo/vX.Y.Z`` syntax).

The version is optional; existing rows get NULL and behave exactly as
before. The unique constraint on (url) is relaxed to (url, version) so
the same site can be crawled at multiple versions.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_doc_versions"
down_revision: Union[str, None] = "006_context_blobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documentation_sources",
        sa.Column("version", sa.String(64), nullable=True),
    )
    # Drop the old single-column unique on (url) and replace with (url, version).
    # ``IF EXISTS`` keeps the migration safe on schemas where 003 was tweaked.
    op.execute(
        "ALTER TABLE documentation_sources "
        "DROP CONSTRAINT IF EXISTS uq_documentation_sources_url"
    )
    op.create_unique_constraint(
        "uq_documentation_sources_url_version",
        "documentation_sources",
        ["url", "version"],
    )
    op.create_index(
        "idx_docs_sources_version",
        "documentation_sources",
        ["url", "version"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_docs_sources_version", table_name="documentation_sources"
    )
    op.drop_constraint(
        "uq_documentation_sources_url_version",
        "documentation_sources",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_documentation_sources_url",
        "documentation_sources",
        ["url"],
    )
    op.drop_column("documentation_sources", "version")
