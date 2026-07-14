"""Executes claimed jobs and commits what they produced."""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from typing import Any, Callable, Dict, Optional

import httpx

from backend.core.config import get_settings
from backend.handlers.base import JobHandler
from backend.handlers.generate_handler import GenerateHandler
from backend.handlers.ingest_handler import IngestHandler
from backend.handlers.refine_handler import RefineHandler
from backend.models.jobs import JobModel, JobType
from backend.services.database import Database, get_database
from backend.services.events import (
    ARTIFACT_CREATED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PROGRESS,
    JOB_STARTED,
    publish,
)
from backend.services.flow import FlowEngine

logger = logging.getLogger(__name__)

TRANSIENT_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)

TRANSIENT_PHRASES = (
    "rate limit",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "connection reset",
    "overloaded",
    "service unavailable",
)

TRANSIENT_STATUS = re.compile(r"\b(?:http|status|code)\s*[:=]?\s*(408|409|425|429|500|502|503|504)\b")


def is_transient(error: BaseException) -> bool:
    """
    Whether a failure is worth retrying.

    A busy upstream will succeed on the next attempt; a malformed payload will
    fail identically while spending tokens.

    Status codes are matched only where they are labelled as one. A bare
    three-digit match would classify any message that happened to contain those
    digits, including artifact identifiers, as retryable.
    """
    if isinstance(error, TRANSIENT_EXCEPTIONS):
        return True

    message = str(error).lower()
    return bool(TRANSIENT_STATUS.search(message)) or any(
        phrase in message for phrase in TRANSIENT_PHRASES
    )


class JobExecutor:
    """
    Runs one job: claim, execute, commit, notify.

    This is the only place a job becomes committed state, which is what lets
    handlers stay pure and keeps a failure from writing a partial graph.
    """

    HANDLERS: Dict[str, Callable[[], JobHandler]] = {
        JobType.INGEST.value: IngestHandler,
        JobType.GENERATE.value: GenerateHandler,
        JobType.REFINE.value: RefineHandler,
    }

    def __init__(self, database: Optional[Database] = None) -> None:
        self._database = database or get_database()
        self._flow = FlowEngine(self._database)
        self._handlers: Dict[str, JobHandler] = {}

    def handler_for(self, job_type: str) -> JobHandler:
        """Build one handler per type and reuse it; construction opens clients."""
        if job_type not in self._handlers:
            build = self.HANDLERS.get(job_type)
            if build is None:
                raise ValueError(f"No handler for job type '{job_type}'")
            self._handlers[job_type] = build()
        return self._handlers[job_type]

    async def execute(self, job: JobModel) -> bool:
        """
        Run a job to completion. Returns whether it committed.

        Never raises: a failed job is an outcome, and the worker loop stays up.
        """
        project_id = str(job.project_id)
        job_type = job.type.value

        publish(project_id, JOB_STARTED, {"job_id": str(job.id), "type": job_type})

        try:
            handler = self.handler_for(job_type).with_progress(
                lambda stage, percent: publish(project_id, JOB_PROGRESS, {
                    "job_id": str(job.id), "stage": stage, "percent": percent,
                })
            )

            bundle = await asyncio.wait_for(
                handler.run(job), timeout=get_settings().job_timeout_seconds
            )
            self._database.commit_bundle(bundle)
            logger.info("Job %s (%s) completed", job.id, job_type)

            for artifact in bundle.artifacts:
                publish(project_id, ARTIFACT_CREATED, {
                    "artifact_id": str(artifact.id), "type": artifact.type, "job_id": str(job.id),
                })
            publish(project_id, JOB_COMPLETED, {
                "job_id": str(job.id), "type": job_type, "result": bundle.result,
            })

            self._notify_flow(job, artifact_id=bundle.result.get("artifact_id"))
            return True

        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._record_failure(job, job_type, project_id, error)
            return False

    async def run_job(self, job_id: str) -> bool:
        """Claim a specific job and execute it."""
        job = self._database.claim_job(job_id)
        if job is None:
            logger.info("Job %s was not claimable; another worker has it", job_id)
            return False
        return await self.execute(job)

    async def run_next(self) -> bool:
        """Claim whatever is at the head of the queue and execute it."""
        job = self._database.claim_job()
        if job is None:
            return False
        await self.execute(job)
        return True

    def _record_failure(self, job: JobModel, job_type: str, project_id: str, error: Exception) -> None:
        retryable = is_transient(error)
        message = str(error) or error.__class__.__name__

        logger.error(
            "Job %s (%s) failed%s: %s\n%s",
            job.id, job_type, " [transient]" if retryable else "", message, traceback.format_exc(),
        )

        try:
            outcome = self._database.fail_job(job.id, message, retryable=retryable)
        except Exception as database_error:
            logger.critical("Could not record the failure of job %s: %s", job.id, database_error)
            outcome = "failed"

        if outcome == "pending":
            logger.info("Job %s requeued for another attempt", job.id)
            return

        publish(project_id, JOB_FAILED, {
            "job_id": str(job.id), "type": job_type, "error": message,
        })
        self._notify_flow(job, error=message)

    def _notify_flow(
        self,
        job: JobModel,
        *,
        artifact_id: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> None:
        if not job.flow_run_id or not job.flow_node_id:
            return

        try:
            from backend.services.dispatcher import enqueue

            self._flow.on_job_finished(
                job.flow_run_id,
                job.flow_node_id,
                artifact_id=str(artifact_id) if artifact_id else None,
                error=error,
                dispatch=enqueue,
            )
        except Exception as flow_error:
            logger.error("Could not advance flow run %s: %s", job.flow_run_id, flow_error)


class WorkerPool:
    """
    Drains the queue inside the API process when Celery is not running.

    A reaper runs alongside the workers, because a process killed mid-job leaves
    its row `running` forever and the node would spin with no error.
    """

    IDLE_BACKOFF_START = 0.5
    IDLE_BACKOFF_LIMIT = 5.0
    REAP_INTERVAL_SECONDS = 60

    def __init__(self, concurrency: Optional[int] = None) -> None:
        settings = get_settings()
        self._concurrency = concurrency or settings.worker_concurrency
        self._stale_after = settings.stale_job_seconds
        self._database = get_database()
        self._executor = JobExecutor(self._database)
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        """Start the workers and the reaper."""
        if self._tasks:
            return

        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._worker(index), name=f"bee-worker-{index}")
            for index in range(self._concurrency)
        ]
        self._tasks.append(asyncio.create_task(self._reaper(), name="bee-reaper"))
        logger.info("Worker pool started (concurrency=%d)", self._concurrency)

    async def stop(self) -> None:
        """Stop every worker and wait for them to unwind."""
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("Worker pool stopped")

    async def _worker(self, index: int) -> None:
        backoff = self.IDLE_BACKOFF_START

        while not self._stopping.is_set():
            try:
                if await self._executor.run_next():
                    backoff = self.IDLE_BACKOFF_START
                    continue
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, self.IDLE_BACKOFF_LIMIT)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("Worker %d error: %s", index, error, exc_info=True)
                await asyncio.sleep(5)

    async def _reaper(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.sleep(self.REAP_INTERVAL_SECONDS)
                reaped = self._database.reap_stale_jobs(self._stale_after)
                if reaped:
                    logger.warning("Requeued %d stale job(s)", len(reaped))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.error("Reaper error: %s", error)
