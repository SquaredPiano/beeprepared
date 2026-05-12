"""
Flow routes: run the canvas as a pipeline.

``POST /api/projects/{id}/flow/validate`` compiles the graph and reports what
would run, without side effects. The canvas calls it as you wire nodes up, so
a cycle or an unconnected generator is shown immediately instead of surfacing as
a failed job later.

``POST /api/projects/{id}/flow/run`` compiles, persists a flow run, and
dispatches the first wave. Everything after that is driven by job completions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_user, get_db, require_project
from backend.api.schemas import (
    FlowPlanResponse,
    FlowRunRequest,
    FlowRunResponse,
    FlowStepView,
    FlowValidateRequest,
)
from backend.services.db_interface import DBInterface
from backend.services.dispatcher import enqueue
from backend.services.flow_engine import FlowEngine, FlowValidationError, compile_flow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["flows"])


def _graph(project: Dict[str, Any], request: FlowRunRequest) -> tuple[List[dict], List[dict]]:
    """
    The graph to run: whatever the client sent, else the saved canvas.

    Taking the client's copy matters - autosave is debounced, so the canvas on
    screen is routinely ahead of what is persisted, and running the stale copy
    would silently ignore the node the user just wired up.
    """
    if request.nodes is not None:
        return request.nodes, request.edges or []

    canvas = project.get("canvas_state") or {}
    return canvas.get("nodes") or [], canvas.get("edges") or []


@router.post("/{project_id}/flow/validate", response_model=FlowPlanResponse)
def validate_flow(
    project_id: str,
    request: FlowValidateRequest,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> FlowPlanResponse:
    """Compile the graph and report the plan, or why it will not run."""
    project = require_project(project_id, user_id, db)
    nodes, edges = _graph(project, request)

    try:
        plan = compile_flow(nodes, edges)
    except FlowValidationError as exc:
        return FlowPlanResponse(valid=False, error=str(exc))

    return FlowPlanResponse(
        valid=True,
        waves=len(plan.waves),
        steps=[
            FlowStepView(
                node_id=step.node_id,
                target_type=step.target_type,
                parents=step.parents,
                depth=step.depth,
            )
            for step in plan.steps
        ],
    )


@router.post("/{project_id}/flow/run", response_model=FlowRunResponse, status_code=202)
def run_flow(
    project_id: str,
    request: FlowRunRequest,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> FlowRunResponse:
    """Start a flow run and dispatch its first wave."""
    project = require_project(project_id, user_id, db)
    nodes, edges = _graph(project, request)

    engine = FlowEngine(db)
    try:
        run = engine.start(project_id, nodes, edges, dispatch=enqueue)
    except FlowValidationError as exc:
        # A malformed graph is the caller's problem to fix, not a server error.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info("Flow run %s started for project %s", run["id"], project_id)
    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})


@router.get("/{project_id}/flow/runs")
def list_flow_runs(
    project_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> List[Dict[str, Any]]:
    require_project(project_id, user_id, db)
    return FlowEngine(db).list_for_project(project_id)


@router.get("/{project_id}/flow/runs/{flow_run_id}", response_model=FlowRunResponse)
def get_flow_run(
    project_id: str,
    flow_run_id: str,
    user_id: str = Depends(get_current_user),
    db: DBInterface = Depends(get_db),
) -> FlowRunResponse:
    """
    The current state of a flow run.

    Live updates arrive over the WebSocket; this exists so a client that
    reconnects can resynchronise without replaying the event stream.
    """
    require_project(project_id, user_id, db)

    run = FlowEngine(db).get(flow_run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})
