"""Celery application: workers that run jobs outside the API process."""

from __future__ import annotations

import logging

from celery import Celery

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

celery_app = Celery(
    "beeprepared",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or None,
    include=["backend.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.job_timeout_seconds + 60,
    task_soft_time_limit=settings.job_timeout_seconds,
    task_max_retries=0,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
)


def broker_available() -> bool:
    """
    Whether the broker is configured and answering.

    Checked before enqueuing so work is never dropped into a queue that has no
    worker draining it.
    """
    if not settings.has_redis or not settings.celery_enabled:
        return False

    try:
        with celery_app.connection_for_write() as connection:
            connection.ensure_connection(max_retries=1, timeout=2)
        return True
    except Exception as error:
        logger.warning("Celery broker unreachable (%s)", error)
        return False
