"""source_visibility

Revision ID: 008_source_visibility
Revises: 007_doc_versions
Create Date: 2026-05-17

Adds a 3-tier ``visibility`` column to every source table — repositories,
papers, documentation_sources, datasets. The legacy boolean ``is_public``
stays for back-compat but is now a derived view:

  visibility='public'  -> is_public True, anyone in the org can list
  visibility='private' -> is_public False, only owner sees it
  visibility='unlisted'-> is_public False, but anyone with the source_id can
                         add to their collection (link-share)

Default for existing rows: copied from is_public (true -> public,
false -> private).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_source_visibility"
down_revision: Union[str, None] = "007_doc_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_visibility(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "visibility",
            sa.String(16),
            nullable=False,
            server_default="public",
        ),
    )
    op.create_index(f"idx_{table}_visibility", table, ["visibility"])
    # Backfill from is_public — runs once and uses the existing column.
    op.execute(
        f"UPDATE {table} SET visibility = CASE WHEN is_public THEN 'public' "
        f"ELSE 'private' END"
    )


def _drop_visibility(table: str) -> None:
    op.drop_index(f"idx_{table}_visibility", table_name=table)
    op.drop_column(table, "visibility")


def upgrade() -> None:
    _add_visibility("repositories")
    _add_visibility("papers")
    _add_visibility("documentation_sources")
    _add_visibility("datasets")


def downgrade() -> None:
    _drop_visibility("datasets")
    _drop_visibility("documentation_sources")
    _drop_visibility("papers")
    _drop_visibility("repositories")
