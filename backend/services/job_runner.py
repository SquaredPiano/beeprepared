"""
Job execution.

``JobRunner`` is the one place a job is turned into committed state. It owns the
transaction boundary and the event stream; handlers own the work.

Execution of a single job:

1. **Claim** it atomically, so two workers cannot pick up the same row.
2. **Run** the handler, forwarding progress to the event bus as it goes.
3. **Commit** the returned bundle in one transaction.
4. **Notify** the flow engine, which may unblock downstream nodes.

Failures are classified before they are recorded. A rate-limited model call is
transient and the job goes back on the queue with an attempt burned; a malformed
payload is permanent and retrying it would only waste tokens.

``WorkerPool`` is the in-process fallback: a bounded set of asyncio workers that
drain the same queue when Redis and Celery are not available. Same executor,
same semantics - only the transport differs.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Dict, Optional

import httpx

from backend.core.config import get_settings
from backend.handlers.base import JobHandler
from backend.handlers.generate_handler import GenerateHandler
from backend.handlers.ingest_handler import IngestHandler
from backend.handlers.refine_handler import RefineHandler
from backend.models.jobs import JobModel, JobType
from backend.services.db_interface import DBInterface
from backend.services.events import (
    EVENT_ARTIFACT_CREATED,
    EVENT_JOB_COMPLETED,
    EVENT_JOB_FAILED,
    EVENT_JOB_PROGRESS,
    EVENT_JOB_STARTED,
    publish,
)
from backend.services.flow_engine import FlowEngine

logger = logging.getLogger(__name__)


# Errors worth retrying: the upstream was busy or the network blinked. Anything
# else (bad payload, missing artifact, schema violation) will fail identically
# on the next attempt, so it is recorded as final.
TRANSIENT_ERRORS = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)

TRANSIENT_MARKERS = (
    "429", "rate limit", "timeout", "timed out", "temporarily unavailable",
    "503", "502", "504", "connection reset", "overloaded",
)


def is_transient(error: BaseException) -> bool:
    """Should this failure be retried?"""
    if isinstance(error, TRANSIENT_ERRORS):
        return True
    message = str(error).lower()
    return any(marker in message for marker in TRANSIENT_MARKERS)


class JobExecutor:
    """Executes a single claimed job and commits its result."""

    def __init__(self, db: Optional[DBInterface] = None):
        self.db = db or DBInterface()
        self.flow_engine = FlowEngine(self.db)
        self._handlers: Dict[str, JobHandler] = {}

    def handler_for(self, job_type: str) -> JobHandler:
        """
        Lazily build and cache one handler instance per type.

        Handlers are stateless but expensive to construct (they open LLM clients
        and storage clients), so building one per job would dominate the runtime
        of a short job.
        """
        if job_type not in self._handlers:
            builders = {
                JobType.INGEST.value: IngestHandler,
                JobType.GENERATE.value: GenerateHandler,
                JobType.REFINE.value: RefineHandler,
            }
            builder = builders.get(job_type)
            if builder is None:
                raise ValueError(f"No handler registered for job type '{job_type}'")
            self._handlers[job_type] = builder()
        return self._handlers[job_type]

    # -- execution ----------------------------------------------------------

    async def execute(self, job: JobModel) -> bool:
        """
        Run one job to completion. Returns True if it committed successfully.

        Never raises: a job failing is an outcome, not an exception the caller
        should handle. The worker loop stays alive.
        """
        project_id = str(job.project_id)
        job_type = job.type.value if hasattr(job.type, "value") else str(job.type)

        publish(project_id, EVENT_JOB_STARTED, {
            "job_id": str(job.id), "type": job_type, "payload": job.payload,
        })

        def on_progress(stage: str, percent: int) -> None:
            publish(project_id, EVENT_JOB_PROGRESS, {
                "job_id": str(job.id), "stage": stage, "percent": percent,
            })

        try:
            handler = self.handler_for(job_type).with_progress(on_progress)

            settings = get_settings()
            bundle = await asyncio.wait_for(
                handler.run(job), timeout=settings.job_timeout_seconds
            )
            if bundle is None:
                raise RuntimeError("Handler returned no bundle")

            self.db.commit_bundle(bundle)
            logger.info("Job %s (%s) completed", job.id, job_type)

            for artifact in bundle.artifacts:
                publish(project_id, EVENT_ARTIFACT_CREATED, {
                    "artifact_id": str(artifact.id),
                    "type": artifact.type,
                    "job_id": str(job.id),
                })
            publish(project_id, EVENT_JOB_COMPLETED, {
                "job_id": str(job.id), "type": job_type, "result": bundle.result,
            })

            self._notify_flow(job, artifact_id=bundle.result.get("artifact_id"))
            return True

        except asyncio.CancelledError:
            raise
        except Exception as error:
            return self._record_failure(job, job_type, project_id, error)

    def _record_failure(self, job: JobModel, job_type: str, project_id: str, error: Exception) -> bool:
        retryable = is_transient(error)
        message = str(error) or error.__class__.__name__

        logger.error(
            "Job %s (%s) failed%s: %s\n%s",
            job.id, job_type, " [transient]" if retryable else "", message,
            traceback.format_exc(),
        )

        try:
            outcome = self.db.fail_job(job.id, message, retryable=retryable)
        except Exception as db_error:
            logger.critical("Could not record failure for job %s: %s", job.id, db_error)
            outcome = "failed"

        if outcome == "pending":
            logger.info("Job %s requeued for another attempt", job.id)
            return False

        publish(project_id, EVENT_JOB_FAILED, {
            "job_id": str(job.id), "type": job_type, "error": message,
        })
        self._notify_flow(job, error=message)
        return False

    def _notify_flow(self, job: JobModel, *, artifact_id=None, error=None) -> None:
        """Tell the flow engine a step finished, so it can schedule the next wave."""
        flow_run_id = job.payload.get("flow_run_id")
        node_id = job.payload.get("flow_node_id")
        if not flow_run_id or not node_id:
            return
        try:
            from backend.services.dispatcher import enqueue

            self.flow_engine.on_job_finished(
                flow_run_id, node_id,
                artifact_id=str(artifact_id) if artifact_id else None,
                error=error,
                dispatch=enqueue,
            )
        except Exception as exc:
            logger.error("Failed to advance flow run %s: %s", flow_run_id, exc)

    async def run_job_id(self, job_id: str) -> bool:
        """Claim a specific job and execute it. Used by the Celery task."""
        job = self.db.claim_job(job_id)
        if job is None:
            # Already claimed by another worker, cancelled, or gone. Not an error.
            logger.info("Job %s was not claimable; skipping", job_id)
            return False
        return await self.execute(job)

    async def run_next(self) -> bool:
        """Claim and run whatever is at the head of the queue."""
        job = self.db.claim_job()
        if job is None:
            return False
        await self.execute(job)
        return True


class WorkerPool:
    """
    In-process worker pool.

    Runs when Celery is unavailable so a plain ``uvicorn backend.main:app`` still
    processes jobs. ``concurrency`` workers poll the same queue; because
    ``claim_job`` is atomic, they never collide on a row.

    A reaper task runs alongside them and returns jobs stranded by a crashed
    worker to the queue - without it, a killed process leaves its job stuck in
    ``running`` forever and the node spins in the UI indefinitely.
    """

    def __init__(self, concurrency: Optional[int] = None):
        settings = get_settings()
        self.concurrency = concurrency or settings.worker_concurrency
        self.stale_after = settings.stale_job_seconds
        self.executor = JobExecutor()
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._tasks:
            return
        self._stopping.clear()
        self._tasks = [
            asyncio.create_task(self._worker(index), name=f"bee-worker-{index}")
            for index in range(self.concurrency)
        ]
        self._tasks.append(asyncio.create_task(self._reaper(), name="bee-reaper"))
        logger.info("Started in-process worker pool (concurrency=%d)", self.concurrency)

    async def stop(self) -> None:
        self._stopping.set()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("Worker pool stopped")

    async def _worker(self, index: int) -> None:
        idle_backoff = 0.5
        while not self._stopping.is_set():
            try:
                worked = await self.executor.run_next()
                # Poll fast while there is work, then back off so an idle
                # deployment is not hammering the database.
                idle_backoff = 0.5 if worked else min(idle_backoff * 1.5, 5.0)
                if not worked:
                    await asyncio.sleep(idle_backoff)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Worker %d loop error: %s", index, exc, exc_info=True)
                await asyncio.sleep(5)

    async def _reaper(self) -> None:
        while not self._stopping.is_set():
            try:
                await asyncio.sleep(60)
                requeued = self.executor.db.reap_stale_jobs(self.stale_after)
                if requeued:
                    logger.warning("Reaped %d stale job(s): %s", len(requeued), requeued)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Reaper error: %s", exc)


# Kept as the module entry point for `python -m backend.services.job_runner`.
async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pool = WorkerPool()
    await pool.start()
    try:
        await asyncio.Event().wait()
    finally:
        await pool.stop()


if __name__ == "__main__":
    asyncio.run(_main())
