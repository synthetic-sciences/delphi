"""Background job queue."""

import time
from collections import deque

_QUEUE: deque = deque()


def enqueue_job(name: str, payload: dict, priority: int = 0) -> str:
    """Add a job to the background queue and return its id."""
    job_id = f"{name}-{int(time.time() * 1000)}"
    _QUEUE.append({"id": job_id, "name": name, "payload": payload, "priority": priority})
    return job_id


def process_queue(handler) -> int:
    """Drain the queue, invoking handler for each job. Returns count processed."""
    processed = 0
    while _QUEUE:
        job = _QUEUE.popleft()
        handler(job)
        processed += 1
    return processed
