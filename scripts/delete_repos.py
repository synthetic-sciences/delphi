"""Delete specific repositories (FastAPI, Pydantic, httpx) from the database.

Usage:
    uv run python scripts/delete_repos.py          # dry-run (shows what would be deleted)
    uv run python scripts/delete_repos.py --confirm # actually delete
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from sqlalchemy import text

from synsc.database.connection import get_session

REPOS_TO_DELETE = ["fastapi", "pydantic", "httpx"]


def main():
    confirm = "--confirm" in sys.argv

    with get_session() as session:
        # Find matching repos
        rows = session.execute(
            text("""
                SELECT repo_id, owner, name, branch, is_public, files_count, chunks_count
                FROM repositories
                WHERE LOWER(name) = ANY(:names)
                ORDER BY owner, name
            """),
            {"names": [n.lower() for n in REPOS_TO_DELETE]},
        ).fetchall()

        if not rows:
            print("No matching repositories found.")
            return

        print(f"Found {len(rows)} repositories:\n")
        for r in rows:
            print(f"  {r.owner}/{r.name} (branch={r.branch}, "
                  f"files={r.files_count}, chunks={r.chunks_count}, "
                  f"public={r.is_public})")
            print(f"    repo_id: {r.repo_id}")

        if not confirm:
            print("\nDry run — pass --confirm to delete.")
            return

        print("\nDeleting...")
        for r in rows:
            rid = str(r.repo_id)

            # chunk_relationships doesn't have repo_id — delete via code_chunks join
            try:
                res = session.execute(
                    text("""
                        DELETE FROM chunk_relationships cr
                        WHERE cr.source_chunk_id IN (
                            SELECT cc.chunk_id FROM code_chunks cc
                            JOIN repository_files rf ON cc.file_id = rf.file_id
                            WHERE rf.repo_id = :rid
                        )
                    """),
                    {"rid": rid},
                )
                if res.rowcount:
                    print(f"  chunk_relationships: deleted {res.rowcount} rows")
            except Exception:
                session.rollback()  # table may not exist yet

            # Delete remaining tables in dependency order
            for table in [
                "chunk_embeddings",
                "symbols",
                "code_chunks",
                "repository_files",
                "user_repositories",
                "repositories",
            ]:
                res = session.execute(
                    text(f"DELETE FROM {table} WHERE repo_id = :rid"),
                    {"rid": rid},
                )
                if res.rowcount:
                    print(f"  {table}: deleted {res.rowcount} rows")
            print(f"  Deleted {r.owner}/{r.name}")

        session.commit()
        print(f"\nDone. Deleted {len(rows)} repositories.")


if __name__ == "__main__":
    main()
