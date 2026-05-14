"""
BeePrepared API.

Application assembly only - routing lives in ``backend/api/routes``. This file
wires middleware, lifespan and error handling, and nothing else. It used to be a
thousand lines containing a hand-rolled Supabase client, the auth logic, and
every endpoint in the product; splitting it means a route can be found by its
filename and tested without importing the world.

Startup does three things:

1. Resolve configuration once - database backend, storage backend, LLM provider,
   dispatch mode - and log the result, so the first line of a support question
   ("what was it actually connected to?") is answered by the logs.
2. Bind the event bus to the running loop, so worker threads can publish onto it.
3. Start the in-process worker pool, but only when Celery is not handling jobs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager

# Allow `python backend/main.py` as well as `uvicorn backend.main:app`.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.env import load_environment

load_environment()

from backend.api.routes import artifacts, chat, files, flows, jobs, projects, ws  # noqa: E402
from backend.core.config import get_settings  # noqa: E402
from backend.core.services.llm_factory import LLMFactory  # noqa: E402
from backend.services import events as event_module  # noqa: E402
from backend.services.db_interface import active_backend, backend_reason  # noqa: E402
from backend.services.dispatcher import dispatch_mode, set_local_pool  # noqa: E402
from backend.services.storage import storage_backend_name  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
for noisy in ("httpx", "httpcore", "botocore", "boto3", "urllib3", "s3transfer"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # An in-process event bus fans out on the loop that owns its queues, and
    # publishers can be worker threads, so it needs a handle on that loop.
    bus = event_module.get_event_bus()
    if isinstance(bus, event_module.MemoryEventBus):
        bus.bind_loop(asyncio.get_running_loop())

    try:
        provider = type(LLMFactory.get_provider()).__name__
    except Exception as exc:
        provider = f"unavailable ({exc})"

    mode = dispatch_mode()
    logger.info(
        "BeePrepared API starting\n"
        "  database : %s (%s)\n"
        "  storage  : %s\n"
        "  events   : %s\n"
        "  jobs     : %s\n"
        "  llm      : %s",
        active_backend(), backend_reason(), storage_backend_name(), bus.driver, mode, provider,
    )

    pool = None
    if mode == "local":
        # No Celery worker is listening, so this process does the work itself.
        from backend.services.job_runner import WorkerPool

        pool = WorkerPool(settings.worker_concurrency)
        await pool.start()
        set_local_pool(pool)

    try:
        yield
    finally:
        if pool is not None:
            await pool.stop()
        logger.info("BeePrepared API stopped")


app = FastAPI(
    title="BeePrepared API",
    description="Turns lecture material into study artifacts through a graph pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()

# `allow_credentials=True` with `allow_origins=["*"]` is rejected by browsers -
# the previous config was effectively no CORS at all. Origins are explicit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://localhost(:\d+)?|https?://127\.0\.0\.1(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """
    Tag every request with an id and log how long it took.

    The id goes back in a header, so a user reporting "generation failed" can be
    traced to the exact request without guessing from timestamps.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        elapsed = (time.perf_counter() - started) * 1000
        logger.exception("[%s] %s %s failed after %.0fms",
                         request_id, request.method, request.url.path, elapsed)
        raise

    elapsed = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    if elapsed > 1000 or response.status_code >= 500:
        logger.warning("[%s] %s %s -> %d (%.0fms)", request_id, request.method,
                       request.url.path, response.status_code, elapsed)
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Return validation failures the frontend can actually display."""
    problems = [
        {"field": ".".join(str(p) for p in error["loc"][1:]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": "Request validation failed", "problems": problems},
    )


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    """Never leak a stack trace to a client; always leave one in the logs."""
    request_id = request.headers.get("X-Request-ID", "-")
    logger.exception("[%s] Unhandled error on %s", request_id, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(artifacts.router)
app.include_router(flows.router)
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(ws.router)


@app.get("/health", tags=["meta"])
def health():
    """
    Liveness plus a description of what this instance is wired to.

    Deliberately more than ``{"status": "ok"}``: most of the confusing failures
    in this system come from being connected to something other than what you
    assumed, and this makes that visible in one request.
    """
    return {
        "status": "healthy",
        "service": "BeePrepared API",
        "version": app.version,
        "database": active_backend(),
        "storage": storage_backend_name(),
        "events": event_module.get_event_bus().driver,
        "jobs": dispatch_mode(),
    }


@app.get("/api/capabilities", tags=["meta"])
def capabilities():
    """What this deployment can produce. The UI builds its palette from this."""
    from backend.models.artifacts import GENERATED_ARTIFACT_TYPES

    return {
        "artifact_types": sorted(GENERATED_ARTIFACT_TYPES),
        "source_types": ["youtube", "audio", "video", "pdf", "pptx", "md"],
        "features": {
            "flows": True,
            "refine": True,
            "assistant": True,
            "realtime": True,
            "offline_llm": LLMFactory.is_offline(),
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
