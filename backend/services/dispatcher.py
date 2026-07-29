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
    Says where jobs actually run, in Celery workers or in this process.

    We work it out once and remember the answer. If the broker answers we use
    Celery, and if it doesn't we fall back to the in-process pool, so someone who
    clones this repo without Redis still gets their jobs run.
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
    Send a job off to the workers, and say how it went out.

    In local mode there's nothing to do here. The pool is already polling and it
    will find the row by itself. Either way the row is committed before we're
    called, so if the broker is down the work turns up late rather than never.
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
