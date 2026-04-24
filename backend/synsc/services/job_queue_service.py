"""Job Queue Service for asynchronous repository indexing.

Uses PostgreSQL as a simple but robust job queue.
Supports:
- Job creation and status tracking
- Progress updates with ETA
- Job cancellation
- Worker coordination
"""

import time
from datetime import datetime, timezone
from typing import Callable

import structlog
from sqlalchemy import and_, func, text

from synsc.database.connection import get_session
from synsc.database.models import IndexingJob

logger = structlog.get_logger(__name__)


class JobQueueService:
    """Service for managing the indexing job queue."""
    
    def __init__(self):
        """Initialize the job queue service."""
        pass
    
    def create_job(
        self,
        user_id: str,
        repo_url: str,
        branch: str = "main",
        priority: int = 0,
    ) -> dict:
        """Create a new indexing job.
        
        Args:
            user_id: User who requested the indexing
            repo_url: GitHub repository URL
            branch: Branch to index
            priority: Job priority (higher = more urgent)
            
        Returns:
            Dict with job details
        """
        with get_session() as session:
            # Check if there's already a pending/processing job for this repo
            existing = session.query(IndexingJob).filter(
                and_(
                    IndexingJob.user_id == user_id,
                    IndexingJob.repo_url == repo_url,
                    IndexingJob.branch == branch,
                    IndexingJob.status.in_(["pending", "processing"]),
                )
            ).first()
            
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
    
    def get_job(self, job_id: str, user_id: str | None = None) -> dict:
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
            if user_id and job.user_id != user_id:
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
    ) -> dict:
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
    
    def cancel_job(self, job_id: str, user_id: str) -> dict:
        """Cancel a pending or processing job.
        
        Args:
            job_id: Job ID
            user_id: User ID for access control
            
        Returns:
            Dict with result
        """
        with get_session() as session:
            job = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id
            ).first()
            
            if not job:
                return {"success": False, "error": "Job not found"}
            
            if job.user_id != user_id:
                return {"success": False, "error": "Access denied"}
            
            if job.status not in ["pending", "processing"]:
                return {
                    "success": False,
                    "error": f"Cannot cancel job in status: {job.status}",
                }
            
            job.status = "cancelled"
            job.completed_at = datetime.now(timezone.utc)
            session.commit()
            
            logger.info("Cancelled job", job_id=job_id, user_id=user_id)
            
            return {
                "success": True,
                "message": "Job cancelled",
                "job": job.to_dict(),
            }
    
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
                        started_at = NOW()
                    WHERE job_id = (
                        SELECT job_id FROM indexing_jobs
                        WHERE status = 'pending'
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
    
    def update_progress(
        self,
        job_id: str,
        progress: float,
        stage: str | None = None,
        message: str | None = None,
        files_total: int | None = None,
        files_processed: int | None = None,
        chunks_created: int | None = None,
        symbols_extracted: int | None = None,
        estimated_seconds: int | None = None,
    ) -> None:
        """Update job progress.
        
        Args:
            job_id: Job ID
            progress: Progress 0.0 to 1.0
            stage: Current stage name
            message: Human-readable message
            files_total: Total files to process
            files_processed: Files processed so far
            chunks_created: Chunks created so far
            symbols_extracted: Symbols extracted so far
            estimated_seconds: Estimated time remaining
        """
        with get_session() as session:
            job = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id
            ).first()
            
            if job:
                job.progress = progress
                if stage:
                    job.current_stage = stage
                if message:
                    job.current_message = message
                if files_total is not None:
                    job.files_total = files_total
                if files_processed is not None:
                    job.files_processed = files_processed
                if chunks_created is not None:
                    job.chunks_created = chunks_created
                if symbols_extracted is not None:
                    job.symbols_extracted = symbols_extracted
                if estimated_seconds is not None:
                    job.estimated_seconds = estimated_seconds
                
                session.commit()
    
    def complete_job(
        self,
        job_id: str,
        repo_id: str | None = None,
        files_processed: int = 0,
        chunks_created: int = 0,
        symbols_extracted: int = 0,
    ) -> None:
        """Mark a job as completed.
        
        Args:
            job_id: Job ID
            repo_id: Created repository ID
            files_processed: Total files processed
            chunks_created: Total chunks created
            symbols_extracted: Total symbols extracted
        """
        with get_session() as session:
            job = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id
            ).first()
            
            if job:
                job.status = "completed"
                job.progress = 1.0
                job.completed_at = datetime.now(timezone.utc)
                job.result_repo_id = repo_id
                job.files_processed = files_processed
                job.chunks_created = chunks_created
                job.symbols_extracted = symbols_extracted
                job.current_stage = "complete"
                job.current_message = "Indexing completed successfully"
                
                session.commit()
                
                logger.info(
                    "Job completed",
                    job_id=job_id,
                    repo_id=repo_id,
                    files=files_processed,
                    chunks=chunks_created,
                )
    
    def fail_job(self, job_id: str, error_message: str) -> None:
        """Mark a job as failed.
        
        Args:
            job_id: Job ID
            error_message: Error description
        """
        with get_session() as session:
            job = session.query(IndexingJob).filter(
                IndexingJob.job_id == job_id
            ).first()
            
            if job:
                job.status = "failed"
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = error_message
                job.current_stage = "error"
                job.current_message = error_message
                
                session.commit()
                
                logger.error(
                    "Job failed",
                    job_id=job_id,
                    error=error_message,
                )
    
    def get_queue_stats(self) -> dict:
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
