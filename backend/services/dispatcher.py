"""Hands a queued job to whichever worker transport is running."""

from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

CELERY = "celery"
LOCAL = "local"

_mode: Optional[str] = None
_lock = threading.Lock()


def dispatch_mode() -> str:
    """
    Whether jobs run in Celery workers or in this process.

    Decided once: Celery when the broker answers, otherwise the in-process pool,
    so a clone with no Redis still processes work.
    """
    global _mode
    if _mode is None:
        with _lock:
            if _mode is None:
                from backend.celery_app import broker_available

                _mode = CELERY if broker_available() else LOCAL
                logger.info("Job dispatch: %s", _mode)
    return _mode


def enqueue(job_id: str) -> str:
    """
    Send a job to the workers and report how it was dispatched.

    In local mode this is a no-op: the pool is already polling and will pick the
    row up. Either way the row is committed first, so a broker outage delays the
    work rather than losing it.
    """
    if dispatch_mode() == LOCAL:
        return LOCAL

    try:
        from backend.tasks import run_job

        run_job.delay(str(job_id))
        return CELERY
    except Exception as error:
        logger.error("Could not enqueue job %s (%s); leaving it pending", job_id, error)
        return "deferred"


def reset() -> None:
    """Forget the cached mode so the next call re-decides."""
    global _mode
    with _lock:
        _mode = None
