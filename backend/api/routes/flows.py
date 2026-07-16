"""Flows: check whether a canvas will run, then run it."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_user, get_db, require_project
from backend.api.schemas import FlowPlanResponse, FlowRequest, FlowRunResponse, FlowStepView
from backend.services.database import Database
from backend.services.dispatcher import enqueue
from backend.services.flow import FlowCompiler, FlowEngine, FlowValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["flows"])


def _graph(project: Dict[str, Any], request: FlowRequest) -> Tuple[List[dict], List[dict]]:
    """
    The graph to compile: whatever the client sent, else the saved canvas.

    Autosave is debounced, so the canvas on screen is routinely ahead of what is
    stored and running the stale copy would ignore the last node connected.
    """
    if request.nodes is not None:
        return request.nodes, request.edges or []

    canvas = project.get("canvas_state") or {}
    return canvas.get("nodes") or [], canvas.get("edges") or []


@router.post("/{project_id}/flow/validate", response_model=FlowPlanResponse)
def validate_flow(
    project_id: str,
    request: FlowRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> FlowPlanResponse:
    """Compile the graph and report the plan, or why it will not run."""
    project = require_project(project_id, user_id, database)
    nodes, edges = _graph(project, request)

    try:
        plan = FlowCompiler().compile(nodes, edges)
    except FlowValidationError as error:
        return FlowPlanResponse(valid=False, error=str(error))

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
    request: FlowRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> FlowRunResponse:
    """Start a flow run and dispatch its first wave."""
    project = require_project(project_id, user_id, database)
    nodes, edges = _graph(project, request)

    try:
        run = FlowEngine(database).start(project_id, nodes, edges, dispatch=enqueue)
    except FlowValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    logger.info("Flow run %s started", run["id"])
    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})


@router.get("/{project_id}/flow/runs")
def list_flow_runs(
    project_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Recent flow runs for a project."""
    require_project(project_id, user_id, database)
    return FlowEngine(database).list_for_project(project_id)


@router.get("/{project_id}/flow/runs/{flow_run_id}", response_model=FlowRunResponse)
def get_flow_run(
    project_id: str,
    flow_run_id: str,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> FlowRunResponse:
    """
    The current state of a flow run.

    Live updates arrive over the WebSocket; this lets a reconnecting client
    resynchronise without replaying the event stream.
    """
    require_project(project_id, user_id, database)

    run = FlowEngine(database).get(flow_run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})
