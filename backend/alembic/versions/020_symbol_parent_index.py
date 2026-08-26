"""index symbols.parent_symbol_id for purge deletes

Revision ID: 020_symbol_parent_index
Revises: 019_file_okapi
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "020_symbol_parent_index"
down_revision: Union[str, None] = "019_file_okapi"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_symbols_parent
        ON symbols (parent_symbol_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_symbols_parent")
