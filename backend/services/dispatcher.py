"""
Job dispatch.

One function - ``enqueue(job_id)`` - hides where the work actually runs:

- **Celery**, when Redis is reachable. Workers are separate processes and scale
  independently of the API.
- **In-process pool**, otherwise. ``uvicorn backend.main:app`` on its own still
  processes jobs, so cloning the repo and running one command gets you a working
  product with no infrastructure.

Either way the job row is already committed as ``pending`` before dispatch is
attempted, so a broker outage delays work rather than losing it - the periodic
drain task picks up anything that was never enqueued.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_MODE: Optional[str] = None
_LOCK = threading.Lock()
_POOL = None  # backend.services.job_runner.WorkerPool, set by start_local_pool


def dispatch_mode() -> str:
    """``"celery"`` or ``"local"``. Decided once per process."""
    global _MODE
    if _MODE is None:
        with _LOCK:
            if _MODE is None:
                from backend.celery_app import celery_available

                _MODE = "celery" if celery_available() else "local"
                logger.info("Job dispatch mode: %s", _MODE)
    return _MODE


def enqueue(job_id: str) -> str:
    """
    Hand a job to whichever worker transport is active.

    Returns the mode used. In local mode this is a no-op: the pool is already
    polling the queue and will pick the row up on its next tick.
    """
    if dispatch_mode() == "celery":
        try:
            from backend.tasks import run_job

            run_job.delay(str(job_id))
            return "celery"
        except Exception as exc:
            # The row stays pending; `drain_queue` will retry it. Do not raise -
            # the user's job was accepted and losing the request would be worse.
            logger.error("Failed to enqueue job %s onto Celery: %s", job_id, exc)
            return "deferred"

    return "local"


def set_local_pool(pool) -> None:
    """Register the in-process pool so it can be shut down cleanly."""
    global _POOL
    _POOL = pool


def get_local_pool():
    return _POOL


def reset() -> None:
    """Forget the cached mode. Used by tests."""
    global _MODE
    with _LOCK:
        _MODE = None
