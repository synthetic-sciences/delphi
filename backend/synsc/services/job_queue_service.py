"""Job Queue Service for asynchronous repository indexing.

Uses PostgreSQL as a simple but robust job queue.
Supports:
- Job creation and status tracking
- Progress updates with ETA
- Job cancellation
- Worker coordination
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, cast

import structlog
from sqlalchemy import and_, or_, text
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from synsc.database.connection import get_session
from synsc.database.models import IndexingJob

logger = structlog.get_logger(__name__)


class JobQueueService:
    """Service for managing the indexing job queue."""

    SOURCE_JOB_TYPES = {"repo", "paper", "dataset", "docs"}

    def __init__(self) -> None:
        """Initialize the job queue service."""
        pass

    @staticmethod
    def _lock_job_identity(
        session: Session,
        *,
        user_id: str,
        job_type: str,
        target: str,
        branch: str | None,
        display_name: str | None,
        options: dict[str, Any],
    ) -> None:
        """Serialize enqueue decisions for one logical job identity."""
        payload = json.dumps(
            {"display_name": display_name, "options": options},
            sort_keys=True,
            separators=(",", ":"),
        )
        identity = "\x1f".join((user_id, job_type, target, branch or "", payload))
        lock_key = int.from_bytes(
            hashlib.sha256(identity.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    @staticmethod
    def _behavior_options(source_type: str, options: dict[str, Any] | None) -> dict[str, Any]:
        """Return only payload options not represented by queue columns."""
        normalized = dict(options or {})
        if source_type == "repo":
            normalized.pop("branch", None)
        return normalized

    @classmethod
    def _matches_payload(
        cls,
        job: IndexingJob,
        *,
        source_type: str,
        display_name: str | None,
        options: dict[str, Any] | None,
    ) -> bool:
        """Compare behavior-changing payload fields for safe deduplication."""
        return (
            job.display_name == display_name
            and cls._behavior_options(source_type, job.options)
            == cls._behavior_options(source_type, options)
        )
    
    def create_job(
        self,
        user_id: str,
        repo_url: str,
        branch: str | None = None,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Create a new indexing job.
        
        Args:
            user_id: User who requested the indexing
            repo_url: GitHub repository URL
            branch: Branch to index. None lets the worker detect the default.
            priority: Job priority (higher = more urgent)
            
        Returns:
            Dict with job details
        """
        with get_session() as session:
            self._lock_job_identity(
                session,
                user_id=user_id,
                job_type="repository",
                target=repo_url,
                branch=branch,
                display_name=None,
                options={},
            )
            # Check if there's already a pending/processing job for this repo
            candidates = session.query(IndexingJob).filter(
                and_(
                    IndexingJob.user_id == user_id,
                    IndexingJob.job_type == "repository",
                    or_(
                        IndexingJob.repo_url == repo_url,
                        IndexingJob.source_url == repo_url,
                    ),
                    IndexingJob.branch == branch,
                    IndexingJob.status.in_(["pending", "processing", "cancelling"]),
                )
            ).all()
            existing = next(
                (
                    job
                    for job in candidates
                    if self._matches_payload(
                        job,
                        source_type="repo",
                        display_name=None,
                        options={},
                    )
                ),
                None,
            )
            
            if existing:
                return {
                    "success": True,
                    "job_id": existing.job_id,
                    "status": existing.status,
                    "message": "Job already exists",
                    "job": existing.to_dict(),
                }
            
            # Create new job
            job = IndexingJob(
                user_id=user_id,
                repo_url=repo_url,
                branch=branch,
                priority=priority,
                status="pending",
            )
            session.add(job)
            session.commit()
            
            logger.info(
                "Created indexing job",
                job_id=job.job_id,
                repo_url=repo_url,
                user_id=user_id,
            )
            
            return {
                "success": True,
                "job_id": job.job_id,
                "status": "pending",
                "message": "Job queued successfully",
                "job": job.to_dict(),
            }

    def create_source_job(
        self,
        *,
        user_id: str,
        source_type: str,
        url: str,
        display_name: str | None = None,
        options: dict[str, Any] | None = None,
        priority: int = 0,
    ) -> dict[str, Any]:
        """Persist a generic source-indexing request for the worker.

        Unlike an in-process ``asyncio`` task, this payload survives API and
        worker restarts. Repository jobs use the historical ``repository``
        job_type internally while preserving the unified API's ``repo`` name
        at the boundary.
        """
        if source_type not in self.SOURCE_JOB_TYPES:
            raise ValueError(f"Unsupported source type: {source_type}")

        job_type = "repository" if source_type == "repo" else source_type
        payload_options = dict(options or {})
        branch = payload_options.get("branch") if source_type == "repo" else None
        behavior_options = self._behavior_options(source_type, payload_options)

        with get_session() as session:
            self._lock_job_identity(
                session,
                user_id=user_id,
                job_type=job_type,
                target=url,
                branch=branch,
                display_name=display_name,
                options=behavior_options,
            )
            target_filter = IndexingJob.source_url == url
            if source_type == "repo":
                target_filter = or_(
                    IndexingJob.source_url == url,
                    IndexingJob.repo_url == url,
                )
            candidates = session.query(IndexingJob).filter(
                IndexingJob.user_id == user_id,
                IndexingJob.job_type == job_type,
                target_filter,
                IndexingJob.branch == branch,
                IndexingJob.status.in_(["pending", "processing", "cancelling"]),
            ).all()
            existing = next(
                (
                    job
                    for job in candidates
                    if self._matches_payload(
                        job,
                        source_type=source_type,
                        display_name=display_name,
                        options=payload_options,
                    )
                ),
                None,
            )

            if existing:
                return {
                    "success": True,
                    "job_id": existing.job_id,
                    "status": existing.status,
                    "message": "Job already exists",
                    "job": existing.to_dict(),
                }

            job = IndexingJob(
                user_id=user_id,
                job_type=job_type,
                repo_url=url if source_type == "repo" else None,
                branch=branch,
                paper_source=url if source_type == "paper" else None,
                source_url=url,
                display_name=display_name,
                options=payload_options,
                priority=priority,
                status="pending",
            )
            session.add(job)
            session.commit()

            logger.info(
                "Created durable source indexing job",
                job_id=job.job_id,
                source_type=source_type,
                source_url=url,
                user_id=user_id,
            )

            return {
                "success": True,
                "job_id": job.job_id,
                "status": "pending",
                "message": "Job queued successfully",
                "job": job.to_dict(),
            }
    
    def get_job(self, job_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Get job status by ID.
        
        Args:
            job_id: Job ID
            user_id: Optional user ID for access control
            
        Returns:
            Dict with job details
        """
        with get_session() as session:
            job = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id
            ).first()
            
            if not job:
                return {
                    "success": False,
                    "error": "Job not found",
                }
            
            # Access control
            if user_id and str(job.user_id) != str(user_id):
                return {
                    "success": False,
                    "error": "Access denied",
                }
            
            return {
                "success": True,
                "job": job.to_dict(),
            }
    
    def list_jobs(
        self,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List jobs for a user.
        
        Args:
            user_id: User ID
            status: Optional status filter
            limit: Max jobs to return
            
        Returns:
            Dict with list of jobs
        """
        with get_session() as session:
            query = session.query(IndexingJob).filter(
                IndexingJob.user_id == user_id
            )
            
            if status:
                query = query.filter(IndexingJob.status == status)
            
            jobs = query.order_by(IndexingJob.created_at.desc()).limit(limit).all()
            
            return {
                "success": True,
                "jobs": [job.to_dict() for job in jobs],
                "count": len(jobs),
            }
    
    def cancel_job(self, job_id: str, user_id: str) -> dict[str, Any]:
        """Cancel a pending or processing job.
        
        Args:
            job_id: Job ID
            user_id: User ID for access control
            
        Returns:
            Dict with result
        """
        with get_session() as session:
            cancelled = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.user_id == user_id,
                IndexingJob.status == "pending",
            ).update(
                {
                    IndexingJob.status: "cancelled",
                    IndexingJob.completed_at: datetime.now(timezone.utc),
                    IndexingJob.worker_id: None,
                    IndexingJob.current_stage: "cancelled",
                    IndexingJob.current_message: "Job cancelled",
                    IndexingJob.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )

            if not cancelled:
                cancelled = session.query(IndexingJob).filter(
                    IndexingJob.job_id == job_id,
                    IndexingJob.user_id == user_id,
                    IndexingJob.status == "processing",
                ).update(
                    {
                        IndexingJob.status: "cancelling",
                        IndexingJob.current_stage: "cancelling",
                        IndexingJob.current_message: "Cancellation requested",
                        IndexingJob.updated_at: datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )

            if not cancelled:
                job = session.query(IndexingJob).filter(
                    IndexingJob.job_id == job_id
                ).first()
                if not job:
                    return {"success": False, "error": "Job not found"}
                if str(job.user_id) != str(user_id):
                    return {"success": False, "error": "Access denied"}
                return {
                    "success": False,
                    "error": f"Cannot cancel job in status: {job.status}",
                }

            session.commit()
            job = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id
            ).first()
            logger.info(
                "Updated job cancellation state",
                job_id=job_id,
                user_id=user_id,
                status=job.status if job else None,
            )

            return {
                "success": True,
                "message": (
                    "Cancellation requested"
                    if job and job.status == "cancelling"
                    else "Job cancelled"
                ),
                "job": job.to_dict() if job else None,
            }

    def acknowledge_cancellation(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        """Make a cooperative cancellation terminal for the current lease."""
        with get_session() as session:
            updated = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.status == "cancelling",
                IndexingJob.worker_id == worker_id,
                IndexingJob.attempt_count == attempt_count,
            ).update(
                {
                    IndexingJob.status: "cancelled",
                    IndexingJob.completed_at: datetime.now(timezone.utc),
                    IndexingJob.current_stage: "cancelled",
                    IndexingJob.current_message: "Job cancelled",
                    IndexingJob.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            session.commit()
            return bool(updated)
    
    def claim_next_job(self, worker_id: str) -> IndexingJob | None:
        """Claim the next available job for processing.
        
        Uses SELECT FOR UPDATE SKIP LOCKED to prevent race conditions.
        
        Args:
            worker_id: Unique worker identifier
            
        Returns:
            IndexingJob or None if no jobs available
        """
        with get_session() as session:
            # Use raw SQL for proper locking
            result = session.execute(
                text("""
                    UPDATE indexing_jobs
                    SET status = 'processing',
                        worker_id = :worker_id,
                        started_at = NOW(),
                        updated_at = NOW(),
                        attempt_count = COALESCE(attempt_count, 0) + 1
                    WHERE job_id = (
                        SELECT job_id FROM indexing_jobs
                        WHERE status = 'pending'
                          AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, 3)
                        ORDER BY priority DESC, created_at ASC
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    )
                    RETURNING *
                """),
                {"worker_id": worker_id}
            )
            
            row = result.fetchone()
            if row:
                session.commit()
                # Fetch the full job object
                job = session.query(IndexingJob).filter(
                    IndexingJob.job_id == row.job_id
                ).first()
                return job
            
            return None

    def recover_stale_jobs(self, stale_after_seconds: int = 21600) -> dict[str, Any]:
        """Recover jobs abandoned by a crashed worker.

        Retryable jobs are returned to ``pending``. Jobs that have exhausted
        their attempt budget are made terminal instead of looping forever.
        The six-hour default avoids stealing legitimate long-running indexes.
        """
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")

        params = {"stale_after_seconds": stale_after_seconds}
        with get_session() as session:
            cancelled = cast(
                CursorResult[Any],
                session.execute(
                    text(
                        """
                        UPDATE indexing_jobs
                        SET status = 'cancelled',
                            completed_at = NOW(),
                            current_stage = 'cancelled',
                            current_message = 'Job cancelled after worker interruption',
                            updated_at = NOW()
                        WHERE status = 'cancelling'
                          AND updated_at < NOW() - (
                              :stale_after_seconds * INTERVAL '1 second'
                          )
                        """
                    ),
                    params,
                ),
            ).rowcount
            requeued = cast(
                CursorResult[Any],
                session.execute(
                    text(
                        """
                        UPDATE indexing_jobs
                        SET status = 'pending',
                            worker_id = NULL,
                            started_at = NULL,
                            current_stage = 'requeued',
                            current_message = 'Recovered after worker interruption',
                            updated_at = NOW()
                        WHERE status = 'processing'
                          AND updated_at < NOW() - (
                              :stale_after_seconds * INTERVAL '1 second'
                          )
                          AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, 3)
                        """
                    ),
                    params,
                ),
            ).rowcount
            failed = cast(
                CursorResult[Any],
                session.execute(
                    text(
                        """
                        UPDATE indexing_jobs
                        SET status = 'failed',
                            worker_id = NULL,
                            completed_at = NOW(),
                            error_message = 'Worker interrupted and retry budget exhausted',
                            current_stage = 'error',
                            current_message = 'Worker interrupted and retry budget exhausted',
                            updated_at = NOW()
                        WHERE status = 'processing'
                          AND updated_at < NOW() - (
                              :stale_after_seconds * INTERVAL '1 second'
                          )
                          AND COALESCE(attempt_count, 0) >= COALESCE(max_attempts, 3)
                        """
                    ),
                    params,
                ),
            ).rowcount
            session.commit()

        if cancelled or requeued or failed:
            logger.warning(
                "Recovered stale indexing jobs",
                cancelled=cancelled,
                requeued=requeued,
                failed=failed,
                stale_after_seconds=stale_after_seconds,
            )
        return {"cancelled": cancelled, "requeued": requeued, "failed": failed}
    
    def update_progress(
        self,
        job_id: str,
        progress: float,
        *,
        worker_id: str,
        attempt_count: int,
        stage: str | None = None,
        message: str | None = None,
        files_total: int | None = None,
        files_processed: int | None = None,
        chunks_created: int | None = None,
        symbols_extracted: int | None = None,
        estimated_seconds: int | None = None,
    ) -> bool:
        """Update job progress.
        
        Args:
            job_id: Job ID
            progress: Progress 0.0 to 1.0
            worker_id: Worker holding the current lease
            attempt_count: Lease generation captured when the job was claimed
            stage: Current stage name
            message: Human-readable message
            files_total: Total files to process
            files_processed: Files processed so far
            chunks_created: Chunks created so far
            symbols_extracted: Symbols extracted so far
            estimated_seconds: Estimated time remaining
        """
        values: dict[Any, Any] = {
            IndexingJob.progress: progress,
            IndexingJob.updated_at: datetime.now(timezone.utc),
        }
        if stage:
            values[IndexingJob.current_stage] = stage
        if message:
            values[IndexingJob.current_message] = message
        if files_total is not None:
            values[IndexingJob.files_total] = files_total
        if files_processed is not None:
            values[IndexingJob.files_processed] = files_processed
        if chunks_created is not None:
            values[IndexingJob.chunks_created] = chunks_created
        if symbols_extracted is not None:
            values[IndexingJob.symbols_extracted] = symbols_extracted
        if estimated_seconds is not None:
            values[IndexingJob.estimated_seconds] = estimated_seconds

        with get_session() as session:
            updated = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.status == "processing",
                IndexingJob.worker_id == worker_id,
                IndexingJob.attempt_count == attempt_count,
            ).update(values, synchronize_session=False)
            session.commit()
            return bool(updated)

    def heartbeat_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        """Refresh a processing job's lease without changing visible progress."""
        with get_session() as session:
            updated = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.status == "processing",
                IndexingJob.worker_id == worker_id,
                IndexingJob.attempt_count == attempt_count,
            ).update(
                {IndexingJob.updated_at: datetime.now(timezone.utc)},
                synchronize_session=False,
            )
            session.commit()
            return bool(updated)
    
    def complete_job(
        self,
        job_id: str,
        repo_id: str | None = None,
        files_processed: int = 0,
        chunks_created: int = 0,
        symbols_extracted: int = 0,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        """Mark a job as completed.
        
        Args:
            job_id: Job ID
            repo_id: Created repository ID
            files_processed: Total files processed
            chunks_created: Total chunks created
            symbols_extracted: Total symbols extracted
        """
        with get_session() as session:
            updated = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.status == "processing",
                IndexingJob.worker_id == worker_id,
                IndexingJob.attempt_count == attempt_count,
            ).update(
                {
                    IndexingJob.status: "completed",
                    IndexingJob.progress: 1.0,
                    IndexingJob.completed_at: datetime.now(timezone.utc),
                    IndexingJob.result_repo_id: repo_id,
                    IndexingJob.files_processed: files_processed,
                    IndexingJob.chunks_created: chunks_created,
                    IndexingJob.symbols_extracted: symbols_extracted,
                    IndexingJob.current_stage: "complete",
                    IndexingJob.current_message: "Indexing completed successfully",
                    IndexingJob.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            session.commit()

            if updated:
                logger.info(
                    "Job completed",
                    job_id=job_id,
                    repo_id=repo_id,
                    files=files_processed,
                    chunks=chunks_created,
                )
            return bool(updated)

    def complete_source_job(
        self,
        job_id: str,
        *,
        source_type: str,
        source_id: str | None,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        """Complete a generic source job and preserve its canonical result ID."""
        values: dict[Any, Any] = {
            IndexingJob.status: "completed",
            IndexingJob.progress: 1.0,
            IndexingJob.completed_at: datetime.now(timezone.utc),
            IndexingJob.result_source_id: source_id,
            IndexingJob.current_stage: "complete",
            IndexingJob.current_message: "Indexing completed successfully",
            IndexingJob.updated_at: datetime.now(timezone.utc),
        }
        if source_type == "repo":
            values[IndexingJob.result_repo_id] = source_id
        elif source_type == "paper":
            values[IndexingJob.result_paper_id] = source_id

        with get_session() as session:
            updated = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.status == "processing",
                IndexingJob.worker_id == worker_id,
                IndexingJob.attempt_count == attempt_count,
            ).update(values, synchronize_session=False)
            session.commit()

            if updated:
                logger.info(
                    "Source indexing job completed",
                    job_id=job_id,
                    source_type=source_type,
                    source_id=source_id,
                )
            return bool(updated)
    
    def fail_job(
        self,
        job_id: str,
        error_message: str,
        *,
        worker_id: str,
        attempt_count: int,
    ) -> bool:
        """Mark a job as failed.
        
        Args:
            job_id: Job ID
            error_message: Error description
        """
        with get_session() as session:
            updated = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id,
                IndexingJob.status == "processing",
                IndexingJob.worker_id == worker_id,
                IndexingJob.attempt_count == attempt_count,
            ).update(
                {
                    IndexingJob.status: "failed",
                    IndexingJob.completed_at: datetime.now(timezone.utc),
                    IndexingJob.error_message: error_message,
                    IndexingJob.current_stage: "error",
                    IndexingJob.current_message: error_message,
                    IndexingJob.updated_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
            session.commit()

            if updated:
                logger.error(
                    "Job failed",
                    job_id=job_id,
                    error=error_message,
                )
            return bool(updated)
    
    def get_queue_stats(self) -> dict[str, Any]:
        """Get queue statistics.
        
        Returns:
            Dict with queue statistics
        """
        with get_session() as session:
            result = session.execute(
                text("""
                    SELECT 
                        status,
                        COUNT(*) as count,
                        AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_duration
                    FROM indexing_jobs
                    GROUP BY status
                """)
            )
            
            stats = {}
            for row in result.fetchall():
                stats[row.status] = {
                    "count": row.count,
                    "avg_duration_seconds": float(row.avg_duration) if row.avg_duration else None,
                }
            
            return {
                "success": True,
                "stats": stats,
                "pending": stats.get("pending", {}).get("count", 0),
                "processing": stats.get("processing", {}).get("count", 0),
            }


# Singleton instance
_job_queue_service: JobQueueService | None = None


def get_job_queue_service() -> JobQueueService:
    """Get the job queue service singleton."""
    global _job_queue_service
    if _job_queue_service is None:
        _job_queue_service = JobQueueService()
    return _job_queue_service
