"""Background worker for processing indexing jobs.

Runs as a separate process, polling the job queue and processing
repositories in the background.

Features:
- Fully parallel pipeline: file reading, chunking, embedding
- Rate-limited Gemini API calls via semaphore
- Thread-safe progress tracking
- Per-batch error isolation (one failure doesn't kill the job)
- Graceful shutdown on SIGINT/SIGTERM
"""

import signal
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from synsc.config import get_config
from synsc.core.chunker import CodeChunker
from synsc.core.git_client import GitClient
from synsc.core.language_detector import detect_language
from synsc.database.connection import get_session
from synsc.database.models import (
    CodeChunk,
    IndexingJob,
    Repository,
    RepositoryFile,
    Symbol,
    UserRepository,
)
from synsc.embeddings.generator import EmbeddingGenerator
from synsc.indexing.vector_store import get_vector_store
from synsc.parsing.registry import get_parser_registry
from synsc.services.job_queue_service import get_job_queue_service

logger = structlog.get_logger(__name__)


class IndexingWorker:
    """Background worker for processing indexing jobs.
    
    All three processing phases run in parallel:
      Phase 1 — Read files + detect languages   (I/O-bound, full parallelism)
      Phase 2 — Chunk + write DB records         (mixed, batched parallelism)
      Phase 3 — Generate embeddings + store      (API-bound, semaphore-gated)
    """
    
    def __init__(self, worker_id: str | None = None, max_workers: int = 4):
        """Initialize the worker.
        
        Args:
            worker_id: Unique worker identifier
            max_workers: Max parallel threads for all phases
        """
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.max_workers = max_workers
        self.config = get_config()
        self.job_queue = get_job_queue_service()
        self.git_client = GitClient()
        self.chunker = CodeChunker()
        self.embedding_generator = EmbeddingGenerator()
        self.vector_store = get_vector_store()
        self.running = True
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)
        
        logger.info(
            "Worker initialized",
            worker_id=self.worker_id,
            max_workers=max_workers,
        )
    
    def _shutdown_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received", worker_id=self.worker_id)
        self.running = False
    
    def run(self, poll_interval: float = 2.0):
        """Run the worker loop.
        
        Polls for new jobs and processes them.
        
        Args:
            poll_interval: Seconds between poll attempts when idle
        """
        logger.info("Worker started", worker_id=self.worker_id)
        
        # Track if we've shown the table missing error
        table_missing_logged = False
        
        while self.running:
            try:
                # Try to claim a job
                job = self.job_queue.claim_next_job(self.worker_id)
                
                # Reset the flag if we successfully queried
                table_missing_logged = False
                
                if job:
                    logger.info(
                        "Processing job",
                        job_id=job.job_id,
                        repo_url=job.repo_url,
                        worker_id=self.worker_id,
                    )
                    self._process_job(job)
                else:
                    # No jobs available, wait before polling again
                    time.sleep(poll_interval)
                    
            except Exception as e:
                error_str = str(e)
                
                # Check if it's the "table doesn't exist" error
                if "indexing_jobs" in error_str and "does not exist" in error_str:
                    if not table_missing_logged:
                        logger.warning(
                            "indexing_jobs table not found - run migration SQL in Supabase. "
                            "Worker will retry silently. Use --no-worker flag to disable.",
                            worker_id=self.worker_id,
                        )
                        table_missing_logged = True
                    # Wait longer before retrying when table is missing
                    time.sleep(poll_interval * 5)
                else:
                    logger.error(
                        "Worker error",
                        error=error_str,
                        worker_id=self.worker_id,
                    )
                    time.sleep(poll_interval)
        
        logger.info("Worker stopped", worker_id=self.worker_id)
    
    def _process_job(self, job: IndexingJob):
        """Process a single indexing job.
        
        Args:
            job: The job to process
        """
        start_time = time.time()
        
        try:
            # Update progress
            self.job_queue.update_progress(
                job.job_id,
                progress=0.05,
                stage="cloning",
                message="Cloning repository...",
            )
            
            # Clone the repository
            repo_info = self.git_client.clone(job.repo_url, job.branch)
            repo_path = Path(repo_info["path"])
            owner = repo_info["owner"]
            name = repo_info["name"]
            commit_sha = repo_info["commit_sha"]
            
            self.job_queue.update_progress(
                job.job_id,
                progress=0.10,
                stage="listing",
                message="Listing files...",
            )
            
            # List files
            files = self.git_client.list_files(repo_path)
            total_files = len(files)
            
            self.job_queue.update_progress(
                job.job_id,
                progress=0.15,
                stage="processing",
                message=f"Processing {total_files} files...",
                files_total=total_files,
            )
            
            # Process files with parallel execution
            result = self._process_files_parallel(
                job=job,
                repo_path=repo_path,
                files=files,
                owner=owner,
                name=name,
                branch=job.branch,
                commit_sha=commit_sha,
                repo_url=job.repo_url,
                user_id=job.user_id,
            )
            
            # Complete the job
            elapsed = time.time() - start_time
            logger.info(
                "Job completed",
                job_id=job.job_id,
                elapsed_seconds=round(elapsed, 1),
                files=result["files_processed"],
                chunks=result["chunks_created"],
                symbols=result["symbols_extracted"],
                embed_errors=result.get("embed_errors", 0),
            )
            
            self.job_queue.complete_job(
                job.job_id,
                repo_id=result["repo_id"],
                files_processed=result["files_processed"],
                chunks_created=result["chunks_created"],
                symbols_extracted=result["symbols_extracted"],
            )
            
        except Exception as e:
            logger.error(
                "Job failed",
                job_id=job.job_id,
                error=str(e),
            )
            self.job_queue.fail_job(job.job_id, str(e))
    
    def _process_files_parallel(
        self,
        job: IndexingJob,
        repo_path: Path,
        files: list[dict],
        owner: str,
        name: str,
        branch: str,
        commit_sha: str,
        repo_url: str,
        user_id: str,
    ) -> dict:
        """Process files through a fully parallel 3-phase pipeline.
        
        Phase 1: Read files + detect languages  (I/O-parallel)
        Phase 2: Chunk + DB writes              (batched-parallel)
        Phase 3: Embed + store vectors           (rate-limited-parallel)
        
        Args:
            job: The indexing job
            repo_path: Path to cloned repo
            files: List of file info dicts
            owner: Repo owner
            name: Repo name
            branch: Branch name
            commit_sha: Commit SHA
            repo_url: Repository URL
            user_id: User ID
            
        Returns:
            Dict with processing results
        """
        parser_registry = get_parser_registry()
        
        # Shared lock for thread-safe counter updates + progress reporting
        _lock = threading.Lock()
        
        # ── Setup: create repository record ──────────────────────────────
        # Determine visibility: check if repo is publicly accessible
        is_public = False
        try:
            import httpx
            resp = httpx.head(repo_url, timeout=5, follow_redirects=True)
            is_public = resp.status_code == 200
        except Exception:
            pass  # Default to private for safety
        
        with get_session() as session:
            repo = Repository(
                url=repo_url,
                owner=owner,
                name=name,
                branch=branch,
                commit_sha=commit_sha,
                is_public=is_public,
                indexed_by=user_id,
            )
            session.add(repo)
            session.flush()
            repo_id = repo.repo_id
            
            # Add to user's collection
            user_repo = UserRepository(user_id=user_id, repo_id=repo_id)
            session.add(user_repo)
            session.commit()
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Phase 1: Read files + detect languages (parallel I/O)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        processed_files: list[dict] = []
        total_files = len(files)
        phase1_progress = {"done": 0}
        
        def read_single_file(file_info: dict) -> dict:
            """Read a single file from disk and detect its language."""
            file_path = file_info["path"]
            full_path = repo_path / file_path
            try:
                content = full_path.read_text(errors="replace")
                language = detect_language(file_path, content)
                return {
                    "file_path": file_path,
                    "content": content,
                    "language": language,
                    "size": len(content),
                    "lines": content.count("\n") + 1,
                    "success": True,
                }
            except Exception as e:
                return {"file_path": file_path, "success": False, "error": str(e)}
        
        self.job_queue.update_progress(
            job.job_id, progress=0.20, stage="reading",
            message="Reading files...", files_total=total_files,
        )
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(read_single_file, f): f for f in files}
            for future in as_completed(futures):
                result = future.result()
                if result["success"]:
                    with _lock:
                        processed_files.append(result)
                with _lock:
                    phase1_progress["done"] += 1
                    done = phase1_progress["done"]
                
                if done % 50 == 0 or done == total_files:
                    progress = 0.20 + (done / total_files) * 0.15
                    self.job_queue.update_progress(
                        job.job_id, progress=progress, stage="reading",
                        message=f"Read {done}/{total_files} files",
                        files_processed=done, files_total=total_files,
                    )
        
        if not processed_files:
            logger.warning("No files to process after reading", job_id=job.job_id)
            return {
                "repo_id": repo_id,
                "files_processed": 0,
                "chunks_created": 0,
                "symbols_extracted": 0,
            }
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Phase 2: Chunk + DB writes (batched-parallel)
        #   Each thread gets its own DB session and file batch.
        #   Failures are isolated per-batch — one bad file doesn't kill
        #   the whole job.
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.job_queue.update_progress(
            job.job_id, progress=0.35, stage="chunking",
            message=f"Chunking {len(processed_files)} files...",
        )
        
        chunks_to_embed: list[tuple[str, str]] = []  # (chunk_id, content)
        phase2 = {"chunks": 0, "symbols": 0, "files_done": 0}
        phase2_errors: list[str] = []
        
        # Distribute files round-robin across worker threads
        n_batches = min(self.max_workers, len(processed_files))
        file_batches: list[list[dict]] = [[] for _ in range(n_batches)]
        for i, fd in enumerate(processed_files):
            file_batches[i % n_batches].append(fd)
        
        def chunk_file_batch(batch: list[dict], batch_idx: int):
            """Process a batch of files: DB records + symbols + chunks.
            
            Each call opens its own DB session so transactions are isolated.
            """
            local_chunks: list[tuple[str, str]] = []
            local_symbols = 0
            local_chunk_count = 0
            
            try:
                with get_session() as session:
                    for file_data in batch:
                        try:
                            # ── Create RepositoryFile record ──
                            db_file = RepositoryFile(
                                repo_id=repo_id,
                                file_path=file_data["file_path"],
                                language=file_data["language"],
                                content_hash=str(hash(file_data["content"])),
                                size_bytes=file_data["size"],
                                line_count=file_data["lines"],
                                token_count=self.chunker.count_tokens(file_data["content"]),
                            )
                            session.add(db_file)
                            session.flush()
                            
                            # ── Extract symbols (optional) ──
                            parser = (
                                parser_registry.get_parser(file_data["language"])
                                if file_data["language"] else None
                            )
                            if parser:
                                try:
                                    extracted = parser.extract_symbols(file_data["content"])
                                    for sym in extracted:
                                        db_symbol = Symbol(
                                            repo_id=repo_id,
                                            file_id=db_file.file_id,
                                            name=sym.name,
                                            qualified_name=sym.qualified_name,
                                            symbol_type=sym.symbol_type,
                                            signature=sym.signature,
                                            docstring=sym.docstring,
                                            start_line=sym.start_line,
                                            end_line=sym.end_line,
                                            is_exported=sym.is_exported,
                                            is_async=sym.is_async,
                                            language=file_data["language"],
                                        )
                                        session.add(db_symbol)
                                        local_symbols += 1
                                except Exception:
                                    pass  # Symbol extraction is best-effort
                            
                            # ── Create code chunks ──
                            chunks = self.chunker.chunk_file(
                                file_data["content"], file_data["language"]
                            )
                            for chunk_idx, chunk in enumerate(chunks):
                                db_chunk = CodeChunk(
                                    repo_id=repo_id,
                                    file_id=db_file.file_id,
                                    chunk_index=chunk_idx,
                                    content=chunk.content,
                                    start_line=chunk.start_line,
                                    end_line=chunk.end_line,
                                    chunk_type=chunk.chunk_type,
                                    language=file_data["language"],
                                    token_count=chunk.token_count,
                                )
                                session.add(db_chunk)
                                session.flush()
                                local_chunks.append((db_chunk.chunk_id, chunk.content))
                                local_chunk_count += 1
                        
                        except Exception as e:
                            # Individual file failure — skip it, keep going
                            logger.warning(
                                "Skipping file (processing error)",
                                file=file_data["file_path"],
                                error=str(e),
                            )
                            continue
                    
                    session.commit()
            
            except Exception as e:
                # Entire batch transaction failed
                with _lock:
                    phase2_errors.append(f"Batch {batch_idx}: {e}")
                logger.error(
                    "Chunk batch transaction failed",
                    batch=batch_idx,
                    files_in_batch=len(batch),
                    error=str(e),
                )
                return
            
            # ── Thread-safe aggregation ──
            with _lock:
                chunks_to_embed.extend(local_chunks)
                phase2["chunks"] += local_chunk_count
                phase2["symbols"] += local_symbols
                phase2["files_done"] += len(batch)
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(chunk_file_batch, batch, i): i
                for i, batch in enumerate(file_batches) if batch
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    batch_idx = futures[future]
                    logger.error("Chunk batch raised unexpectedly", batch=batch_idx, error=str(e))
                
                # Report progress after each batch completes
                with _lock:
                    done = phase2["files_done"]
                progress = 0.35 + (done / len(processed_files)) * 0.20
                self.job_queue.update_progress(
                    job.job_id, progress=min(progress, 0.55), stage="chunking",
                    message=f"Chunked {done}/{len(processed_files)} files",
                    chunks_created=phase2["chunks"],
                    symbols_extracted=phase2["symbols"],
                )
        
        chunks_created = phase2["chunks"]
        symbols_extracted = phase2["symbols"]
        
        if phase2_errors:
            logger.warning(
                "Phase 2 completed with errors",
                error_count=len(phase2_errors),
                errors=phase2_errors[:5],
            )
        
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # Phase 3: Embedding generation + storage (rate-limited parallel)
        #   Gemini API calls are gated by a semaphore to avoid 429s.
        #   DB writes happen outside the semaphore so they don't block
        #   the next API call (pipeline parallelism).
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        self.job_queue.update_progress(
            job.job_id, progress=0.55, stage="embeddings",
            message=f"Generating embeddings for {len(chunks_to_embed)} chunks...",
        )
        
        embed_error_count = 0
        
        if chunks_to_embed:
            embed_batch_size = self.embedding_generator.batch_size
            embed_batches = [
                chunks_to_embed[i : i + embed_batch_size]
                for i in range(0, len(chunks_to_embed), embed_batch_size)
            ]
            total_embed_batches = len(embed_batches)
            embed_progress = {"done": 0}
            embed_errors: list[str] = []
            
            # Gate concurrent Gemini API calls — 2 in-flight is safe;
            # remaining threads pipeline the DB storage of prior results.
            max_concurrent_api = min(2, self.max_workers)
            api_semaphore = threading.Semaphore(max_concurrent_api)
            
            def embed_and_store(batch: list[tuple[str, str]], batch_num: int):
                """Generate embeddings for one batch and store in pgvector.
                
                Retry logic handles transient Gemini 429s with exponential
                backoff.  DB writes happen outside the semaphore so they
                overlap with the next API call.
                """
                chunk_ids = [c[0] for c in batch]
                contents = [c[1] for c in batch]
                
                # ── Rate-limited Gemini API call ──
                embeddings = None
                max_retries = 4
                with api_semaphore:
                    for attempt in range(max_retries):
                        try:
                            embeddings = self.embedding_generator.generate(contents)
                            break
                        except Exception as e:
                            err = str(e)
                            is_rate_limit = any(
                                marker in err.lower()
                                for marker in ["429", "quota", "rate", "resource_exhausted"]
                            )
                            if is_rate_limit and attempt < max_retries - 1:
                                wait = 2 ** (attempt + 1)  # 2s, 4s, 8s, 16s
                                logger.warning(
                                    "Gemini rate-limited, backing off",
                                    wait_seconds=wait,
                                    attempt=attempt + 1,
                                    batch=batch_num,
                                )
                                time.sleep(wait)
                            else:
                                raise
                
                if embeddings is None:
                    raise RuntimeError(
                        f"Embedding generation failed after {max_retries} retries "
                        f"(batch {batch_num})"
                    )
                
                # ── Store in DB (outside semaphore — no rate limit on PG) ──
                self.vector_store.add(
                    embeddings=embeddings,
                    chunk_ids=chunk_ids,
                    repo_id=repo_id,
                )
                
                # ── Thread-safe progress update ──
                with _lock:
                    embed_progress["done"] += 1
                    current = embed_progress["done"]
                
                progress = 0.55 + (current / total_embed_batches) * 0.40
                self.job_queue.update_progress(
                    job.job_id, progress=min(progress, 0.95), stage="embeddings",
                    message=f"Embedded batch {current}/{total_embed_batches}",
                )
            
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(embed_and_store, batch, i + 1): i
                    for i, batch in enumerate(embed_batches)
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        batch_idx = futures[future]
                        embed_errors.append(f"Batch {batch_idx + 1}: {e}")
                        logger.error(
                            "Embedding batch failed (skipped)",
                            batch=batch_idx + 1,
                            total=total_embed_batches,
                            error=str(e),
                        )
            
            embed_error_count = len(embed_errors)
            if embed_errors:
                logger.warning(
                    "Phase 3 completed with errors",
                    failed=len(embed_errors),
                    total=total_embed_batches,
                    succeeded=total_embed_batches - len(embed_errors),
                    sample_errors=embed_errors[:3],
                )
        
        # ── Finalize: update repository stats ────────────────────────────
        with get_session() as session:
            repo = session.query(Repository).filter(
                Repository.repo_id == repo_id
            ).first()
            if repo:
                repo.files_count = len(processed_files)
                repo.chunks_count = chunks_created
                repo.symbols_count = symbols_extracted
                session.commit()
        
        return {
            "repo_id": repo_id,
            "files_processed": len(processed_files),
            "chunks_created": chunks_created,
            "symbols_extracted": symbols_extracted,
            "embed_errors": embed_error_count,
        }


def run_worker(worker_id: str | None = None, max_workers: int = 4):
    """Run the indexing worker.
    
    Args:
        worker_id: Optional worker ID
        max_workers: Max parallel threads
    """
    worker = IndexingWorker(worker_id=worker_id, max_workers=max_workers)
    worker.run()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run indexing worker")
    parser.add_argument("--worker-id", help="Worker ID")
    parser.add_argument("--max-workers", type=int, default=4, help="Max parallel threads")
    
    args = parser.parse_args()
    run_worker(worker_id=args.worker_id, max_workers=args.max_workers)
