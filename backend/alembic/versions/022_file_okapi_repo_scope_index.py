"""index file-level Okapi documents by repository scope

Revision ID: 022_file_okapi_repo_scope_index
Revises: 021_file_okapi_compact
Create Date: 2026-08-24
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "022_file_okapi_repo_scope_index"
down_revision: Union[str, None] = "021_file_okapi_compact"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_file_lexical_documents_repo
        ON repository_file_lexical_documents (repo_id, index_version)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_file_lexical_documents_repo")
