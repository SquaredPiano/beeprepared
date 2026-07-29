"""Celery tasks. Each one delegates to the same executor the local pool uses."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Dict

from backend.celery_app import celery_app
from backend.core.config import get_settings
from backend.services.database import get_database

logger = logging.getLogger(__name__)

DRAIN_INTERVAL_SECONDS = 120.0
REAP_INTERVAL_SECONDS = 300.0


def _run(coroutine: Coroutine) -> Any:
    """
    Run a coroutine to completion from Celery's synchronous worker.

    We shut the loop's executor down along with the loop itself. The pipeline
    hands ffmpeg and document parsing off to worker threads, and closing the loop
    without waiting on those threads leaks a few of them on every single task.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coroutine)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        asyncio.set_event_loop(None)
        loop.close()


@celery_app.task(name="beeprepared.run_job")
def run_job(job_id: str) -> Dict[str, Any]:
    """Execute one queued job."""
    from backend.services.job_runner import JobExecutor

    logger.info("Running job %s", job_id)
    return {"job_id": job_id, "committed": _run(JobExecutor().run_job(job_id))}


@celery_app.task(name="beeprepared.drain_queue")
def drain_queue() -> Dict[str, int]:
    """
    Enqueue pending jobs that no Celery task is carrying.

    A job becomes a database row before it becomes a message, so the row can sit
    there with nothing on the queue for it. This picks up whatever got written
    while the broker or the workers were down.
    """
    pending = get_database().pending_job_ids()
    for job_id in pending:
        run_job.delay(job_id)

    if pending:
        logger.info("Re-dispatched %d pending job(s)", len(pending))
    return {"requeued": len(pending)}


@celery_app.task(name="beeprepared.reap_stale_jobs")
def reap_stale_jobs() -> Dict[str, int]:
    """
    Hand jobs back to the queue after the worker running them died.

    A worker killed mid-job leaves its row sitting at `running` forever, and
    `claim_job` only ever looks at pending rows, so nothing will pick that job up
    again. The node it belongs to just spins, and nothing raises to say why.
    """
    reaped = get_database().reap_stale_jobs(get_settings().stale_job_seconds)
    for job_id in reaped:
        run_job.delay(job_id)

    if reaped:
        logger.warning("Reaped %d stale job(s)", len(reaped))
    return {"reaped": len(reaped)}


celery_app.conf.beat_schedule = {
    "drain-pending-jobs": {"task": "beeprepared.drain_queue", "schedule": DRAIN_INTERVAL_SECONDS},
    "reap-stale-jobs": {"task": "beeprepared.reap_stale_jobs", "schedule": REAP_INTERVAL_SECONDS},
}
