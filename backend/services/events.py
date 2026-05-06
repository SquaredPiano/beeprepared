"""
Project event bus - the transport behind the WebSocket API.

Job progress is produced by whichever process happens to run the job (a Celery
worker, or the in-process fallback pool) and consumed by WebSocket connections
living in the API process. Those are not the same process, so an in-memory
pub/sub is not enough on its own.

Two drivers:

- ``RedisEventBus``   - Redis pub/sub. Works across processes and machines.
- ``MemoryEventBus``  - asyncio queues. Single process, zero dependencies.

The bus is chosen at startup based on whether Redis is reachable. Publishers
are sync-friendly (workers are not always async) while subscribers are async
iterators, which is what a WebSocket handler wants.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional, Set

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

# Event names are part of the frontend contract. Keep them stable.
EVENT_JOB_CREATED = "job.created"
EVENT_JOB_STARTED = "job.started"
EVENT_JOB_PROGRESS = "job.progress"
EVENT_JOB_COMPLETED = "job.completed"
EVENT_JOB_FAILED = "job.failed"
EVENT_JOB_CANCELLED = "job.cancelled"
EVENT_ARTIFACT_CREATED = "artifact.created"
EVENT_FLOW_STARTED = "flow.started"
EVENT_FLOW_NODE_UPDATE = "flow.node"
EVENT_FLOW_COMPLETED = "flow.completed"
EVENT_FLOW_FAILED = "flow.failed"
EVENT_CHAT_MESSAGE = "chat.message"


def channel_for(project_id: str) -> str:
    return f"beeprepared:project:{project_id}"


def make_event(event_type: str, project_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "type": event_type,
        "project_id": str(project_id),
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": payload or {},
    }


class EventBus(ABC):
    driver: str = "unknown"

    @abstractmethod
    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        """Fan an event out to every subscriber of ``project_id``."""

    @abstractmethod
    async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Async-iterate events for ``project_id`` until the consumer stops."""

    async def aclose(self) -> None:  # pragma: no cover - driver specific
        return None


# ---------------------------------------------------------------------------
# In-process
# ---------------------------------------------------------------------------

class MemoryEventBus(EventBus):
    """
    Single-process bus backed by asyncio queues.

    ``publish`` is callable from any thread: it hops onto the loop that owns the
    subscriber queues via ``call_soon_threadsafe`` rather than touching the
    queue directly, because ``asyncio.Queue`` is not thread-safe.
    """

    driver = "memory"

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _deliver(self, project_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            queues = list(self._subscribers.get(str(project_id), ()))
        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping event for project %s: subscriber queue full", project_id)

    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            self._deliver(project_id, event)
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            self._deliver(project_id, event)
        else:
            loop.call_soon_threadsafe(self._deliver, str(project_id), event)

    async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        key = str(project_id)
        with self._lock:
            self._subscribers.setdefault(key, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                subscribers = self._subscribers.get(key)
                if subscribers:
                    subscribers.discard(queue)
                    if not subscribers:
                        self._subscribers.pop(key, None)


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

class RedisEventBus(EventBus):
    """
    Cross-process bus over Redis pub/sub.

    Publishing uses a sync client so Celery workers (which are not async) can
    emit progress without spinning up an event loop; subscribing uses the async
    client so a WebSocket handler can await messages.
    """

    driver = "redis"

    def __init__(self, url: str):
        import redis

        self.url = url
        self._sync = redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)
        self._sync.ping()
        self._async_client = None

    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        try:
            self._sync.publish(channel_for(str(project_id)), json.dumps(event))
        except Exception as exc:
            logger.warning("Redis publish failed for project %s: %s", project_id, exc)

    async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
        import redis.asyncio as aioredis

        client = aioredis.from_url(self.url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel_for(str(project_id)))
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                try:
                    yield json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Discarding malformed event on %s", message.get("channel"))
        finally:
            await pubsub.unsubscribe(channel_for(str(project_id)))
            await pubsub.aclose()
            await client.aclose()


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_BUS: Optional[EventBus] = None
_BUS_LOCK = threading.Lock()


def _build_bus() -> EventBus:
    settings = get_settings()
    if settings.has_redis:
        try:
            bus = RedisEventBus(settings.redis_url)
            logger.info("Event bus: redis (%s)", settings.redis_url)
            return bus
        except Exception as exc:
            logger.warning("Redis unavailable for events (%s). Using in-process event bus.", exc)
    logger.info("Event bus: in-process")
    return MemoryEventBus()


def get_event_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        with _BUS_LOCK:
            if _BUS is None:
                _BUS = _build_bus()
    return _BUS


def reset_event_bus() -> None:
    global _BUS
    with _BUS_LOCK:
        _BUS = None


def publish(project_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convenience wrapper: build the envelope and publish it."""
    event = make_event(event_type, str(project_id), payload)
    get_event_bus().publish(str(project_id), event)
    return event
