"""Carries job and flow progress from whichever process runs the work."""

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

QUEUE_SIZE = 256

JOB_CREATED = "job.created"
JOB_STARTED = "job.started"
JOB_PROGRESS = "job.progress"
JOB_COMPLETED = "job.completed"
JOB_FAILED = "job.failed"
JOB_CANCELLED = "job.cancelled"
ARTIFACT_CREATED = "artifact.created"
FLOW_STARTED = "flow.started"
FLOW_NODE = "flow.node"
FLOW_COMPLETED = "flow.completed"
FLOW_FAILED = "flow.failed"
CHAT_MESSAGE = "chat.message"


def make_event(event_type: str, project_id: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Wrap a payload in the envelope every client expects."""
    return {
        "type": event_type,
        "project_id": str(project_id),
        "ts": datetime.now(timezone.utc).isoformat(),
        "data": data or {},
    }


class EventBus(ABC):
    """
    Fans project events out to whoever is listening.

    Publishing is callable from any thread because workers are not async;
    subscribing is an async iterator because WebSocket handlers are.
    """

    driver: str = "unknown"

    @abstractmethod
    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        """Deliver an event to every subscriber of this project."""

    @abstractmethod
    def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
        """Yield events for this project until the consumer stops."""


class InProcessEventBus(EventBus):
    """
    Delivers events through asyncio queues within one process.

    Publishers may be worker threads, so delivery hops onto the loop that owns
    the queues rather than touching them directly.
    """

    driver = "memory"

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that owns the subscriber queues."""
        self._loop = loop

    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            self._deliver(str(project_id), event)
            return

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            self._deliver(str(project_id), event)
        else:
            loop.call_soon_threadsafe(self._deliver, str(project_id), event)

    async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
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

    def _deliver(self, project_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            queues = list(self._subscribers.get(project_id, ()))

        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping an event for project %s: subscriber is behind", project_id)


class RedisEventBus(EventBus):
    """Delivers events across processes over Redis pub/sub."""

    driver = "redis"

    def __init__(self, url: str) -> None:
        import redis

        self._url = url
        self._client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=5)
        self._client.ping()

    def publish(self, project_id: str, event: Dict[str, Any]) -> None:
        try:
            self._client.publish(self._channel(project_id), json.dumps(event))
        except Exception as error:
            logger.warning("Redis publish failed for project %s: %s", project_id, error)

    async def subscribe(self, project_id: str) -> AsyncIterator[Dict[str, Any]]:
        import redis.asyncio as redis

        client = redis.from_url(self._url, decode_responses=True)
        channel = self._channel(project_id)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)

        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                try:
                    yield json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Discarding a malformed event on %s", channel)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await client.aclose()

    @staticmethod
    def _channel(project_id: str) -> str:
        return f"beeprepared:project:{project_id}"


_bus: Optional[EventBus] = None
_lock = threading.Lock()


def build_bus() -> EventBus:
    """Use Redis when it is reachable, otherwise stay in process."""
    settings = get_settings()
    if settings.has_redis:
        try:
            return RedisEventBus(settings.redis_url)
        except Exception as error:
            logger.warning("Redis unavailable for events (%s). Staying in process.", error)
    return InProcessEventBus()


def get_event_bus() -> EventBus:
    """The shared event bus, created on first use."""
    global _bus
    if _bus is None:
        with _lock:
            if _bus is None:
                _bus = build_bus()
                logger.info("Event bus: %s", _bus.driver)
    return _bus


def reset_event_bus() -> None:
    """Discard the cached bus so the next call rebuilds it."""
    global _bus
    with _lock:
        _bus = None


def publish(project_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Build an event envelope and publish it."""
    get_event_bus().publish(str(project_id), make_event(event_type, str(project_id), data))
