"""FastAPI application assembly."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import artifacts, chat, files, flows, jobs, projects, ws
from backend.core.config import get_settings
from backend.llm.factory import get_provider
from backend.models.artifacts import GENERATED_TYPES, SOURCE_TYPES
from backend.services import events
from backend.services.database import get_database
from backend.services.dispatcher import LOCAL, dispatch_mode
from backend.services.files import get_file_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

SLOW_REQUEST_MS = 1000
REQUEST_ID_HEADER = "X-Request-ID"

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resolve every dependency once, then start workers if nothing else will."""
    bus = events.get_event_bus()
    if isinstance(bus, events.InProcessEventBus):
        bus.bind_loop(asyncio.get_running_loop())

    database = get_database()
    store = get_file_store()
    provider = get_provider()
    mode = dispatch_mode()

    logger.info(
        "BeePrepared starting\n  database : %s\n  files    : %s\n  events   : %s\n"
        "  jobs     : %s\n  model    : %s",
        database.path, store.root, bus.driver, mode, provider.name,
    )

    pool = None
    if mode == LOCAL:
        from backend.services.job_runner import WorkerPool

        pool = WorkerPool()
        await pool.start()

    try:
        yield
    finally:
        if pool:
            await pool.stop()
        logger.info("BeePrepared stopped")


app = FastAPI(
    title="BeePrepared API",
    description="Turns lecture material into study artifacts through a graph pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)


@app.middleware("http")
async def trace_request(request: Request, call_next):
    """Tag each request with an id and log the slow ones."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception("[%s] %s %s failed", request_id, request.method, request.url.path)
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers[REQUEST_ID_HEADER] = request_id

    if elapsed_ms > SLOW_REQUEST_MS or response.status_code >= 500:
        logger.warning("[%s] %s %s -> %d (%.0fms)", request_id, request.method,
                       request.url.path, response.status_code, elapsed_ms)

    return response


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, error: RequestValidationError):
    """Return field-level problems the frontend can display."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed",
            "problems": [
                {"field": ".".join(str(part) for part in item["loc"][1:]), "message": item["msg"]}
                for item in error.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, error: Exception):
    """Keep stack traces in the logs, not in responses."""
    request_id = request.headers.get(REQUEST_ID_HEADER, "-")
    logger.exception("[%s] Unhandled error on %s", request_id, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


for router in (projects, jobs, artifacts, flows, files, chat, ws):
    app.include_router(router.router)


@app.get("/health", tags=["meta"])
def health():
    """Liveness, plus what this instance resolved its dependencies to."""
    return {
        "status": "healthy",
        "version": app.version,
        "database": str(get_database().path),
        "files": str(get_file_store().root),
        "events": events.get_event_bus().driver,
        "jobs": dispatch_mode(),
        "model": get_provider().name,
    }


@app.get("/api/capabilities", tags=["meta"])
def capabilities():
    """What this deployment can produce. The canvas builds its palette from this."""
    provider = get_provider()
    return {
        "artifact_types": sorted(GENERATED_TYPES),
        "source_types": sorted(SOURCE_TYPES),
        "features": {
            "flows": True,
            "refine": True,
            "assistant": True,
            "realtime": True,
            "transcription": provider.supports_audio,
            "offline_model": provider.name == "offline",
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
