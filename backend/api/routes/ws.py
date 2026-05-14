"""
WebSocket API: live project updates.

Replaces the polling loop the frontend used to run - a fetch every two seconds
per in-flight job, per open tab, each one costing a database round trip and an
auth check, and still showing progress up to two seconds late.

Now the client opens one socket per project and receives job and flow events as
they happen, from whichever process produced them (the event bus is Redis-backed
when Redis is available, so a Celery worker's progress reaches an API process it
never met).

Connection lifecycle
--------------------
1. Client connects to ``/ws/projects/{id}?token=...`` - the token is a query
   parameter because browsers cannot set headers on a WebSocket handshake.
2. The server authenticates, checks project ownership, and accepts.
3. A ``snapshot`` frame is sent first with current job state, so a client that
   connects mid-job renders correctly instead of waiting for the next event.
4. Events stream until either side disconnects.

Two background tasks run per connection: one pumping events out, one reading
frames in. The reader is what makes a dead connection detectable - without it a
half-open socket would sit there consuming a subscription forever.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.api.deps import require_project, resolve_user
from backend.services.db_interface import DBInterface
from backend.services.events import get_event_bus, make_event

logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])

# Ping this often. Idle proxies commonly cut connections at 60s, so the socket
# has to prove it is alive well before that.
HEARTBEAT_SECONDS = 25

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403


def _snapshot(db: DBInterface, project_id: str) -> Dict[str, Any]:
    """Current in-flight state, sent immediately on connect."""
    jobs = db.select(
        "jobs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=20
    )
    flow_runs = db.select(
        "flow_runs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=3
    )
    return {
        "jobs": [
            {
                "id": job["id"],
                "type": job["type"],
                "status": job["status"],
                "result": job.get("result"),
                "error_message": job.get("error_message"),
            }
            for job in jobs
        ],
        "flow_runs": [
            {"id": run["id"], "status": run["status"], "node_states": run.get("node_states")}
            for run in flow_runs
        ],
    }


@router.websocket("/ws/projects/{project_id}")
async def project_socket(
    websocket: WebSocket,
    project_id: str,
    token: str = Query(None),
) -> None:
    """Stream job and flow events for one project."""
    db = DBInterface()

    # Authenticate before accepting: an unauthenticated peer should never get an
    # open socket, even briefly.
    try:
        user_id = resolve_user(f"Bearer {token}" if token else None)
        require_project(project_id, user_id, db)
    except HTTPException as exc:
        code = CLOSE_FORBIDDEN if exc.status_code == 403 else CLOSE_UNAUTHORIZED
        await websocket.close(code=code, reason=str(exc.detail))
        return
    except Exception as exc:
        logger.warning("WebSocket auth error for project %s: %s", project_id, exc)
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="Authentication failed")
        return

    await websocket.accept()
    logger.info("WebSocket open: project=%s user=%s", project_id, user_id)

    try:
        await websocket.send_json(make_event("snapshot", project_id, _snapshot(db, project_id)))
    except Exception as exc:
        logger.debug("Could not send the initial snapshot: %s", exc)

    bus = get_event_bus()

    async def pump_events() -> None:
        """Forward bus events to the client until it goes away."""
        try:
            async for event in bus.subscribe(project_id):
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                await websocket.send_json(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Event pump for project %s ended: %s", project_id, exc)

    async def heartbeat() -> None:
        """Keep the connection warm through idle proxies."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_SECONDS)
                if websocket.client_state != WebSocketState.CONNECTED:
                    return
                await websocket.send_json(make_event("ping", project_id))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Heartbeat for project %s ended: %s", project_id, exc)

    async def read_client() -> None:
        """
        Consume inbound frames.

        The client mostly sends nothing, but reading is what surfaces a
        disconnect - and it lets a client request a fresh snapshot after a
        suspend/resume without tearing the socket down.
        """
        try:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "resync":
                    await websocket.send_json(
                        make_event("snapshot", project_id, _snapshot(db, project_id))
                    )
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("WebSocket reader for project %s ended: %s", project_id, exc)

    tasks = [
        asyncio.create_task(pump_events(), name="ws-events"),
        asyncio.create_task(heartbeat(), name="ws-heartbeat"),
        asyncio.create_task(read_client(), name="ws-reader"),
    ]
    try:
        # Whichever finishes first ends the connection: the reader returning
        # means the client hung up, and either sender returning means the socket
        # is no longer writable.
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        # Cancel without awaiting. The handler is often itself being cancelled
        # at this point, and awaiting here would just raise again before the
        # remaining tasks could be reaped by the loop.
        for task in tasks:
            task.cancel()
        logger.info("WebSocket closed: project=%s", project_id)
