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
from backend.services.dispatcher import enqueue
from backend.services.events import (
    ARTIFACT_CREATED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PROGRESS,
    JOB_STARTED,
    publish,
)
from backend.services.flow import FlowEngine
from backend.services.flow.engine import Dispatch

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
    Decide whether a failure is worth another attempt.

    An upstream that was busy will probably work on the next try. A malformed
    payload will fail in exactly the same way and spend more tokens doing it, so
    retrying it buys us nothing.

    Note that we only read a status code where the message actually labels it as
    one, as in `status: 429` or `HTTP 502`. Matching a bare three-digit number was
    too loose. An error quoting an artifact id with 429 in it got retried as if
    we'd been rate limited, and so did anything along the lines of "artifact 504
    has no content".
    """
    if isinstance(error, TRANSIENT_EXCEPTIONS):
        return True

    message = str(error).lower()
    return bool(TRANSIENT_STATUS.search(message)) or any(
        phrase in message for phrase in TRANSIENT_PHRASES
    )


class JobExecutor:
    """
    Runs a single job, from claiming it through to committing and notifying.

    This is the one place where a job's work turns into committed state. That's
    what lets the handlers stay pure. They work out a bundle and hand it over, so
    when one dies partway through there's no half-written graph to clean up.
    """

    HANDLERS: Dict[str, Callable[[], JobHandler]] = {
        JobType.INGEST.value: IngestHandler,
        JobType.GENERATE.value: GenerateHandler,
        JobType.REFINE.value: RefineHandler,
    }

    def __init__(
        self,
        database: Optional[Database] = None,
        dispatch: Optional[Dispatch] = None,
    ) -> None:
        self._database = database or get_database()
        self._flow = FlowEngine(self._database)
        self._dispatch = dispatch or enqueue
        self._handlers: Dict[str, JobHandler] = {}

    def handler_for(self, job_type: str) -> JobHandler:
        """
        Build a handler for this job type once, then keep handing the same one back.

        Constructing one opens clients, and we'd rather not do that for every job.
        The catch is that the instance you get is shared by every job this executor
        runs, and one executor serves the whole worker pool. So treat it as
        read-only. Anything that has to differ per job comes from `with_progress`,
        which gives you a copy and leaves the shared instance alone.
        """
        if job_type not in self._handlers:
            build = self.HANDLERS.get(job_type)
            if build is None:
                raise ValueError(f"No handler for job type '{job_type}'")
            self._handlers[job_type] = build()
        return self._handlers[job_type]

    async def execute(self, job: JobModel) -> bool:
        """
        Run a job the whole way through, and report back whether it committed.

        This never raises. A job failing is a normal outcome around here, not a
        crash, and the worker loop that called us has to stay up for the next one.
        Cancellation is the one thing we let through, so that shutting the pool
        down doesn't get quietly swallowed.
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
        """Claim one specific job and run it. Returns False if it wasn't there to claim."""
        job = self._database.claim_job(job_id)
        if job is None:
            logger.info("Job %s was not claimable; another worker has it", job_id)
            return False
        return await self.execute(job)

    async def run_next(self) -> bool:
        """
        Take whatever is at the head of the queue and run it.

        True means there was something to run, not that it succeeded. The worker
        loop uses this to tell a busy queue from an idle one.
        """
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
            self._redispatch(job.id)
            return

        if outcome not in {"failed", "missing"}:
            logger.warning(
                "Job %s already finished as %s; leaving that outcome alone", job.id, outcome
            )
            return

        publish(project_id, JOB_FAILED, {
            "job_id": str(job.id), "type": job_type, "error": message,
        })
        self._notify_flow(job, error=message)

    def _redispatch(self, job_id: Any) -> None:
        """
        Push a job we've just requeued back out to the workers.

        By the time we get here `fail_job` has already committed the row as
        `pending`. Commit first, dispatch second, which is the order every dispatch
        in this codebase follows. Skip this call and the retry just sits there
        until something else sweeps the queue, and under Celery the only thing that
        sweeps it is the periodic drain. Take the beat schedule away and the job
        never runs again.

        If the dispatcher itself throws, we log it and stop there. We're already in
        the failure path for a job that went wrong, and `execute` has promised its
        caller it won't raise.
        """
        try:
            self._dispatch(str(job_id))
        except Exception as dispatch_error:
            logger.error("Could not re-dispatch job %s: %s", job_id, dispatch_error)

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
            self._flow.on_job_finished(
                job.flow_run_id,
                job.flow_node_id,
                artifact_id=str(artifact_id) if artifact_id else None,
                error=error,
                dispatch=self._dispatch,
            )
        except Exception as flow_error:
            logger.error("Could not advance flow run %s: %s", job.flow_run_id, flow_error)


class WorkerPool:
    """
    Works the queue inside the API process when there's no Celery to do it.

    A reaper task runs alongside the workers. If this process gets killed mid-job,
    the row it was working on stays `running` for good, and the node on the canvas
    would sit there spinning with nothing to show the user.
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
