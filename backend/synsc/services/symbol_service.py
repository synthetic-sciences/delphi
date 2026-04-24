"""Symbol service for searching and retrieving code symbols.

Uses smart deduplication with access control:
- Users can only search symbols in repos they have access to
- Public repos: must be in user's collection
- Private repos: only the indexer can access
"""

from pathlib import Path

import structlog
from sqlalchemy import func, or_, text
from sqlalchemy.orm import joinedload

from synsc.database.connection import get_session
from synsc.database.models import Repository, RepositoryFile, Symbol, UserRepository

logger = structlog.get_logger(__name__)


class SymbolService:
    """Service for symbol search and retrieval.
    
    Provides functionality to search for code symbols (functions, classes, methods)
    and retrieve detailed symbol information.
    
    ACCESS CONTROL: Only searches symbols in repos the user has access to.
    """
    
    def __init__(self, user_id: str | None = None):
        """Initialize the symbol service.
        
        Args:
            user_id: User ID for access control.
        """
        self.user_id = user_id
    
    def search_symbols(
        self,
        name: str | None,
        repo_ids: list[str] | None = None,
        symbol_type: str | None = None,
        language: str | None = None,
        top_k: int = 25,
        offset: int = 0,
        user_id: str | None = None,
    ) -> dict:
        """Search for symbols by name.
        
        Uses case-insensitive partial matching on symbol name and qualified name.
        OPTIMIZED: Uses raw SQL with JOINs instead of ORM subqueries for speed.
        
        Args:
            name: Symbol name to search for (partial match supported)
            repo_ids: Optional list of repository IDs to limit search
            symbol_type: Filter by type: "function", "class", "method"
            language: Filter by programming language
            top_k: Page size (results per page)
            offset: Pagination offset
            user_id: User ID for multi-tenant filtering (overrides constructor)
            
        Returns:
            Dict with success status, list of matching symbols, and pagination info
        """
        effective_user_id = user_id or self.user_id
        
        # Require user_id
        if not effective_user_id:
            return {
                "success": False,
                "error": "Authentication required",
                "message": "You must be authenticated to search symbols",
            }
        
        # If no search term, delegate to browse_symbols
        if not name or not name.strip():
            return self.browse_symbols(
                repo_ids=repo_ids,
                symbol_type=symbol_type,
                language=language,
                top_k=top_k,
                offset=offset,
                user_id=user_id,
            )
        
        try:
            with get_session() as session:
                # Use raw SQL for maximum performance - avoids ORM overhead
                name_lower = name.lower()
                name_pattern = f"%{name_lower}%"
                
                params = {
                    "user_id": effective_user_id,
                    "name_pattern": name_pattern,
                    "name_exact": name_lower,
                    "top_k": top_k,
                    "offset": offset,
                }
                
                # Build optional filters
                extra_filters = ""
                if repo_ids and len(repo_ids) > 0:
                    # Use IN clause with individual parameters for compatibility
                    repo_placeholders = ", ".join([f":repo_id_{i}" for i in range(len(repo_ids))])
                    extra_filters += f" AND s.repo_id IN ({repo_placeholders})"
                    for i, rid in enumerate(repo_ids):
                        params[f"repo_id_{i}"] = rid
                if symbol_type:
                    extra_filters += " AND s.symbol_type = :symbol_type"
                    params["symbol_type"] = symbol_type
                if language:
                    extra_filters += " AND s.language = :language"
                    params["language"] = language
                
                # Get total count for pagination
                count_result = session.execute(
                    text(f"""
                        WITH user_repos AS MATERIALIZED (
                            SELECT repo_id FROM user_repositories WHERE user_id = :user_id
                        )
                        SELECT COUNT(*) as total
                        FROM symbols s
                        INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
                        INNER JOIN repositories r ON s.repo_id = r.repo_id
                            AND (r.is_public = TRUE OR r.indexed_by = :user_id)
                        WHERE (lower(s.name) LIKE :name_pattern OR lower(s.qualified_name) LIKE :name_pattern)
                        {extra_filters}
                    """),
                    params
                )
                total_count = count_result.scalar() or 0
                
                # OPTIMIZED: Single query with all JOINs, no N+1 problems
                result = session.execute(
                    text(f"""
                        WITH user_repos AS MATERIALIZED (
                            SELECT repo_id FROM user_repositories WHERE user_id = :user_id
                        )
                        SELECT 
                            s.symbol_id,
                            s.name,
                            s.qualified_name,
                            s.symbol_type,
                            s.signature,
                            LEFT(s.docstring, 200) as docstring,
                            LENGTH(s.docstring) as docstring_len,
                            rf.file_path,
                            s.start_line,
                            s.end_line,
                            s.repo_id,
                            r.owner,
                            r.name as repo_name,
                            s.language,
                            s.is_async,
                            s.is_exported
                        FROM symbols s
                        INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
                        INNER JOIN repositories r ON s.repo_id = r.repo_id
                            AND (r.is_public = TRUE OR r.indexed_by = :user_id)
                        INNER JOIN repository_files rf ON s.file_id = rf.file_id
                        WHERE (lower(s.name) LIKE :name_pattern OR lower(s.qualified_name) LIKE :name_pattern)
                        {extra_filters}
                        ORDER BY 
                            (lower(s.name) = :name_exact) DESC,
                            length(s.name),
                            s.name
                        LIMIT :top_k OFFSET :offset
                    """),
                    params
                )
                
                symbols = []
                for row in result.fetchall():
                    docstring = row.docstring
                    if docstring and row.docstring_len > 200:
                        docstring = docstring + "..."
                    
                    symbols.append({
                        "symbol_id": str(row.symbol_id),
                        "name": row.name,
                        "qualified_name": row.qualified_name,
                        "symbol_type": row.symbol_type,
                        "signature": row.signature,
                        "docstring": docstring,
                        "file_path": row.file_path,
                        "start_line": row.start_line,
                        "end_line": row.end_line,
                        "repo_id": str(row.repo_id),
                        "repo_name": f"{row.owner}/{row.repo_name}",
                        "language": row.language,
                        "is_async": row.is_async,
                        "is_exported": row.is_exported,
                    })
                
                return {
                    "success": True,
                    "symbols": symbols,
                    "count": len(symbols),
                    "total": total_count,
                    "page_size": top_k,
                    "offset": offset,
                    "has_more": offset + len(symbols) < total_count,
                }
                
        except Exception as e:
            logger.error("Symbol search failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Symbol search failed: {e}",
            }
    
    def browse_symbols(
        self,
        repo_ids: list[str] | None = None,
        symbol_type: str | None = None,
        language: str | None = None,
        top_k: int = 25,
        offset: int = 0,
        user_id: str | None = None,
    ) -> dict:
        """Browse all symbols without search term.
        
        Returns symbols with optional filters and pagination.
        
        Args:
            repo_ids: Optional list of repository IDs to limit
            symbol_type: Filter by type: "function", "class", "method"
            language: Filter by programming language
            top_k: Page size (results per page)
            offset: Pagination offset
            user_id: User ID for multi-tenant filtering
            
        Returns:
            Dict with success status, list of symbols, and pagination info
        """
        effective_user_id = user_id or self.user_id
        
        if not effective_user_id:
            return {
                "success": False,
                "error": "Authentication required",
                "message": "You must be authenticated to browse symbols",
            }
        
        try:
            with get_session() as session:
                params = {
                    "user_id": effective_user_id,
                    "top_k": top_k,
                    "offset": offset,
                }
                
                # Build optional filters
                extra_filters = ""
                if repo_ids and len(repo_ids) > 0:
                    # Use IN clause with individual parameters for compatibility
                    repo_placeholders = ", ".join([f":repo_id_{i}" for i in range(len(repo_ids))])
                    extra_filters += f" AND s.repo_id IN ({repo_placeholders})"
                    for i, rid in enumerate(repo_ids):
                        params[f"repo_id_{i}"] = rid
                if symbol_type:
                    extra_filters += " AND s.symbol_type = :symbol_type"
                    params["symbol_type"] = symbol_type
                if language:
                    extra_filters += " AND s.language = :language"
                    params["language"] = language
                
                # Get total count for pagination
                count_result = session.execute(
                    text(f"""
                        WITH user_repos AS MATERIALIZED (
                            SELECT repo_id FROM user_repositories WHERE user_id = :user_id
                        )
                        SELECT COUNT(*) as total
                        FROM symbols s
                        INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
                        INNER JOIN repositories r ON s.repo_id = r.repo_id
                            AND (r.is_public = TRUE OR r.indexed_by = :user_id)
                        WHERE 1=1
                        {extra_filters}
                    """),
                    params
                )
                total_count = count_result.scalar() or 0
                
                # Get paginated results
                result = session.execute(
                    text(f"""
                        WITH user_repos AS MATERIALIZED (
                            SELECT repo_id FROM user_repositories WHERE user_id = :user_id
                        )
                        SELECT 
                            s.symbol_id,
                            s.name,
                            s.qualified_name,
                            s.symbol_type,
                            s.signature,
                            LEFT(s.docstring, 150) as docstring,
                            rf.file_path,
                            s.start_line,
                            s.end_line,
                            s.repo_id,
                            r.owner,
                            r.name as repo_name,
                            s.language,
                            s.is_async,
                            s.is_exported
                        FROM symbols s
                        INNER JOIN user_repos ur ON s.repo_id = ur.repo_id
                        INNER JOIN repositories r ON s.repo_id = r.repo_id
                            AND (r.is_public = TRUE OR r.indexed_by = :user_id)
                        INNER JOIN repository_files rf ON s.file_id = rf.file_id
                        WHERE 1=1
                        {extra_filters}
                        ORDER BY r.indexed_at DESC, s.symbol_type, s.name
                        LIMIT :top_k OFFSET :offset
                    """),
                    params
                )
                
                symbols = []
                for row in result.fetchall():
                    symbols.append({
                        "symbol_id": str(row.symbol_id),
                        "name": row.name,
                        "qualified_name": row.qualified_name,
                        "symbol_type": row.symbol_type,
                        "signature": row.signature,
                        "docstring": row.docstring,
                        "file_path": row.file_path,
                        "start_line": row.start_line,
                        "end_line": row.end_line,
                        "repo_id": str(row.repo_id),
                        "repo_name": f"{row.owner}/{row.repo_name}",
                        "language": row.language,
                        "is_async": row.is_async,
                        "is_exported": row.is_exported,
                    })
                
                return {
                    "success": True,
                    "symbols": symbols,
                    "count": len(symbols),
                    "total": total_count,
                    "page_size": top_k,
                    "offset": offset,
                    "has_more": offset + len(symbols) < total_count,
                }
                
        except Exception as e:
            logger.error("Browse symbols failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Browse symbols failed: {e}",
            }
    
    def get_symbol(self, symbol_id: str, user_id: str | None = None) -> dict:
        """Get full symbol details by ID.
        
        OPTIMIZED: Uses eager loading to avoid N+1 queries.
        
        Args:
            symbol_id: Symbol identifier (UUID)
            user_id: User ID for authorization (required in multi-tenant mode)
            
        Returns:
            Dict with success status and full symbol details
        """
        effective_user_id = user_id or self.user_id
        
        try:
            with get_session() as session:
                # OPTIMIZED: Eager load relationships in single query
                symbol = (
                    session.query(Symbol)
                    .options(
                        joinedload(Symbol.file),
                        joinedload(Symbol.repository)
                    )
                    .filter(Symbol.symbol_id == symbol_id)
                    .first()
                )
                
                if not symbol:
                    # Log for debugging
                    logger.warning(
                        "Symbol not found",
                        symbol_id=symbol_id,
                        symbol_id_type=type(symbol_id).__name__,
                    )
                    return {
                        "success": False,
                        "error": "Symbol not found",
                        "message": f"Symbol with ID '{symbol_id}' not found",
                    }
                
                # Access control check
                repo = symbol.repository
                if not repo.can_user_access(effective_user_id):
                    return {
                        "success": False,
                        "error": "Access denied",
                        "message": "You don't have access to this private repository",
                    }
                
                return {
                    "success": True,
                    "symbol_id": str(symbol.symbol_id),
                    "name": symbol.name,
                    "qualified_name": symbol.qualified_name,
                    "symbol_type": symbol.symbol_type,
                    "signature": symbol.signature,
                    "docstring": symbol.docstring,
                    "file_path": symbol.file.file_path,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                    "repo_id": str(symbol.repo_id),
                    "repo_name": f"{symbol.repository.owner}/{symbol.repository.name}",
                    "language": symbol.language,
                    "is_async": symbol.is_async,
                    "is_exported": symbol.is_exported,
                    "parameters": symbol.get_parameters(),
                    "return_type": symbol.return_type,
                    "decorators": symbol.get_decorators(),
                }
                
        except Exception as e:
            logger.error("Get symbol failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to get symbol: {e}",
            }
    
    def get_symbol_by_qualified_name(
        self,
        repo_id: str,
        qualified_name: str,
    ) -> dict:
        """Get symbol by fully qualified name.
        
        Args:
            repo_id: Repository identifier
            qualified_name: Fully qualified symbol name (e.g., "MyClass.method")
            
        Returns:
            Dict with success status and full symbol details
        """
        try:
            with get_session() as session:
                symbol = session.query(Symbol).filter(
                    Symbol.repo_id == repo_id,
                    Symbol.qualified_name == qualified_name,
                ).first()
                
                if not symbol:
                    return {
                        "success": False,
                        "error": "Symbol not found",
                        "message": f"Symbol '{qualified_name}' not found in repository",
                    }
                
                return self.get_symbol(symbol.symbol_id)
                
        except Exception as e:
            logger.error("Get symbol by name failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to get symbol: {e}",
            }
    
    def get_file_symbols(
        self,
        repo_id: str,
        file_path: str,
    ) -> dict:
        """Get all symbols in a file.
        
        Args:
            repo_id: Repository identifier
            file_path: Path to file within repository
            
        Returns:
            Dict with success status and list of symbols
        """
        try:
            with get_session() as session:
                # Get the file
                file = session.query(RepositoryFile).filter(
                    RepositoryFile.repo_id == repo_id,
                    RepositoryFile.file_path == file_path,
                ).first()
                
                if not file:
                    return {
                        "success": False,
                        "error": "File not found",
                        "message": f"File '{file_path}' not found in repository",
                    }
                
                symbols = session.query(Symbol).filter(
                    Symbol.file_id == file.file_id,
                ).order_by(Symbol.start_line).all()
                
                return {
                    "success": True,
                    "file_path": file_path,
                    "symbols": [
                        {
                            "symbol_id": str(s.symbol_id),
                            "name": s.name,
                            "qualified_name": s.qualified_name,
                            "symbol_type": s.symbol_type,
                            "signature": s.signature,
                            "start_line": s.start_line,
                            "end_line": s.end_line,
                            "is_async": s.is_async,
                        }
                        for s in symbols
                    ],
                    "count": len(symbols),
                }
                
        except Exception as e:
            logger.error("Get file symbols failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to get file symbols: {e}",
            }
    
    def get_repo_symbol_stats(self, repo_id: str) -> dict:
        """Get symbol statistics for a repository.
        
        Args:
            repo_id: Repository identifier
            
        Returns:
            Dict with symbol counts by type
        """
        try:
            with get_session() as session:
                # Count by type
                counts = session.query(
                    Symbol.symbol_type,
                    func.count(Symbol.symbol_id),
                ).filter(
                    Symbol.repo_id == repo_id,
                ).group_by(Symbol.symbol_type).all()
                
                type_counts = {t: c for t, c in counts}
                total = sum(type_counts.values())
                
                return {
                    "success": True,
                    "repo_id": repo_id,
                    "total_symbols": total,
                    "by_type": type_counts,
                }
                
        except Exception as e:
            logger.error("Get symbol stats failed", error=str(e))
            return {
                "success": False,
                "error": str(e),
            }
