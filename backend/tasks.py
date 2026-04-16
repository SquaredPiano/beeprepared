"""
Celery tasks.

Deliberately thin. Each task claims a job and delegates to ``JobExecutor``, the
same class the in-process worker pool uses, so a job behaves identically whether
it ran through Redis or not.

Celery workers are synchronous processes while handlers are async, so each task
runs its coroutine on a loop it owns for the duration of the call.
"""

from __future__ import annotations

import asyncio
import logging

from backend.celery_app import celery_app
from backend.core.config import get_settings
from backend.services.db_interface import DBInterface

logger = logging.getLogger(__name__)


def _run(coro):
    """Run a coroutine to completion from Celery's synchronous context."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        # Let cancelled tasks (HTTP clients, semaphores) unwind before closing.
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


@celery_app.task(name="beeprepared.run_job", bind=True)
def run_job(self, job_id: str) -> dict:
    """Execute one queued job."""
    from backend.services.job_runner import JobExecutor

    logger.info("Celery picked up job %s (task=%s)", job_id, self.request.id)
    executor = JobExecutor()
    ok = _run(executor.run_job_id(job_id))
    return {"job_id": job_id, "committed": ok}


@celery_app.task(name="beeprepared.drain_queue")
def drain_queue() -> dict:
    """
    Enqueue any job sitting in ``pending`` that has no Celery task behind it.

    Jobs are rows first and messages second: the API writes the row, then
    enqueues. If the enqueue fails - broker blip, API restart between the two -
    the row would otherwise sit there forever. This is the safety net, and it is
    also what picks up work created while the workers were down.
    """
    pending = DBInterface().pending_job_ids()
    for job_id in pending:
        run_job.delay(job_id)
    if pending:
        logger.info("Drained %d pending job(s) onto the queue", len(pending))
    return {"requeued": len(pending)}


@celery_app.task(name="beeprepared.reap_stale_jobs")
def reap_stale_jobs() -> dict:
    """Return jobs stranded in ``running`` by a dead worker back to the queue."""
    settings = get_settings()
    requeued = DBInterface().reap_stale_jobs(settings.stale_job_seconds)
    for job_id in requeued:
        run_job.delay(job_id)
    if requeued:
        logger.warning("Reaped %d stale job(s)", len(requeued))
    return {"reaped": len(requeued)}


# Periodic maintenance. Both tasks are idempotent, so a missed beat is harmless.
celery_app.conf.beat_schedule = {
    "drain-pending-jobs": {
        "task": "beeprepared.drain_queue",
        "schedule": 120.0,
    },
    "reap-stale-jobs": {
        "task": "beeprepared.reap_stale_jobs",
        "schedule": 300.0,
    },
}
