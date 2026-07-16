"""Streams a project's job and flow events to the browser."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.api.deps import require_project, resolve_user
from backend.services.database import Database, get_database
from backend.services.events import get_event_bus, make_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

HEARTBEAT_SECONDS = 25
SNAPSHOT_JOBS = 20
SNAPSHOT_FLOW_RUNS = 3
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403


@router.websocket("/ws/projects/{project_id}")
async def project_events(websocket: WebSocket, project_id: str, token: str = Query(None)) -> None:
    """
    Stream events for one project.

    The token arrives as a query parameter because browsers cannot set headers
    on a WebSocket handshake, and it is checked before the socket is accepted.
    """
    database = get_database()

    try:
        user_id = resolve_user(f"Bearer {token}" if token else None)
        require_project(project_id, user_id, database)
    except HTTPException as error:
        code = CLOSE_FORBIDDEN if error.status_code == 403 else CLOSE_UNAUTHORIZED
        await websocket.close(code=code, reason=str(error.detail))
        return

    await websocket.accept()
    logger.info("WebSocket open for project %s", project_id)

    await _send_snapshot(websocket, database, project_id)

    tasks = [
        asyncio.create_task(_forward_events(websocket, project_id), name="ws-events"),
        asyncio.create_task(_heartbeat(websocket, project_id), name="ws-heartbeat"),
        asyncio.create_task(_read_client(websocket, database, project_id), name="ws-reader"),
    ]

    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        logger.info("WebSocket closed for project %s", project_id)


async def _forward_events(websocket: WebSocket, project_id: str) -> None:
    """Push bus events to the client until it goes away."""
    try:
        async for event in get_event_bus().subscribe(project_id):
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            await websocket.send_json(event)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.debug("Event stream for %s ended: %s", project_id, error)


async def _heartbeat(websocket: WebSocket, project_id: str) -> None:
    """Keep the connection alive through idle proxies."""
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await websocket.send_json(make_event("ping", project_id))
    except asyncio.CancelledError:
        raise
    except Exception:
        return


async def _read_client(websocket: WebSocket, database: Database, project_id: str) -> None:
    """
    Consume inbound frames.

    Reading is what makes a dropped connection detectable, and it lets a client
    ask for a fresh snapshot after waking from sleep.
    """
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "resync":
                await _send_snapshot(websocket, database, project_id)
    except (WebSocketDisconnect, asyncio.CancelledError):
        raise
    except Exception as error:
        logger.debug("Client stream for %s ended: %s", project_id, error)


async def _send_snapshot(websocket: WebSocket, database: Database, project_id: str) -> None:
    """Send current state so a client joining mid-run renders correctly."""
    try:
        await websocket.send_json(make_event("snapshot", project_id, _snapshot(database, project_id)))
    except Exception as error:
        logger.debug("Could not send a snapshot for %s: %s", project_id, error)


def _snapshot(database: Database, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    jobs = database.select(
        "jobs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=SNAPSHOT_JOBS
    )
    runs = database.select(
        "flow_runs", [("project_id", f"eq.{project_id}")],
        order="created_at.desc", limit=SNAPSHOT_FLOW_RUNS,
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
            for run in runs
        ],
    }
