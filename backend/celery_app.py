"""
Celery application.

Jobs used to run inside the API process on an ``asyncio.create_task`` loop
started at FastAPI startup. That had three problems worth naming:

- **No isolation.** A long LLM call in a job competed with HTTP request handling
  in the same process.
- **No horizontal scale.** Adding API replicas multiplied the pollers, and each
  one raced the others for the same rows.
- **No durability.** Restart the API mid-job and the work was simply gone.

Celery over Redis fixes all three: workers are separate processes that can be
scaled independently of the API, and the broker keeps the queue.

The task itself stays thin. It claims the job and hands it to ``JobExecutor``,
which is the same code path the in-process fallback uses - so behaviour does not
diverge between "running with Redis" and "running without it".
"""

from __future__ import annotations

import logging

from celery import Celery

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Redis is the broker; results are kept there too. Job outcomes are also written
# to the database, so the result backend is only for task-level bookkeeping.
BROKER_URL = settings.redis_url or "memory://"

celery_app = Celery(
    "beeprepared",
    broker=BROKER_URL,
    backend=settings.redis_url or None,
    include=["backend.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # Fetch one task at a time. Jobs here are long and uneven, so prefetching
    # would let one worker sit on a queue of work while another idles.
    worker_prefetch_multiplier=1,

    # Acknowledge only after the task returns, so a worker that dies mid-job
    # hands the message back to the broker instead of dropping it.
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    task_time_limit=settings.job_timeout_seconds + 60,   # hard kill
    task_soft_time_limit=settings.job_timeout_seconds,   # raises inside the task

    # Retries are decided per-job by the executor (transient vs permanent), so
    # Celery's blanket autoretry stays off.
    task_default_retry_delay=30,
    task_max_retries=0,

    broker_connection_retry_on_startup=True,
    result_expires=3600,
)


def celery_available() -> bool:
    """
    Can we actually reach the broker?

    Checked before enqueuing so the dispatcher can fall back to the in-process
    pool instead of silently dropping work into a queue nobody is draining.
    """
    if not settings.has_redis or not settings.celery_enabled:
        return False
    try:
        with celery_app.connection_for_write() as connection:
            connection.ensure_connection(max_retries=1, timeout=2)
        return True
    except Exception as exc:
        logger.warning("Celery broker unreachable (%s)", exc)
        return False
