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
false -> private). New papers default to private; the other source types
default to public.

The migration deliberately uses idempotent DDL because setup_local.sql is a
baseline that may already contain the columns when Alembic upgrades it.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008_source_visibility"
down_revision: str | None = "007_doc_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_visibility(table: str, default: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS visibility VARCHAR(16)")
    op.execute(
        f"UPDATE {table} SET visibility = CASE WHEN is_public THEN 'public' "
        "ELSE 'private' END WHERE visibility IS NULL"
    )
    op.execute(f"ALTER TABLE {table} ALTER COLUMN visibility SET DEFAULT '{default}'")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN visibility SET NOT NULL")
    op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_visibility ON {table}(visibility)")


def _drop_visibility(table: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS idx_{table}_visibility")
    op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS visibility")


def upgrade() -> None:
    _add_visibility("repositories", "public")
    _add_visibility("papers", "private")
    _add_visibility("documentation_sources", "public")
    _add_visibility("datasets", "public")


def downgrade() -> None:
    _drop_visibility("datasets")
    _drop_visibility("documentation_sources")
    _drop_visibility("papers")
    _drop_visibility("repositories")
