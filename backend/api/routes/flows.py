"""Flows: check whether a canvas will run, then run it."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_user, get_db, require_project, require_project_artifact
from backend.api.schemas import FlowPlanResponse, FlowRequest, FlowRunResponse, FlowStepView
from backend.services.database import Database
from backend.services.dispatcher import enqueue
from backend.services.flow import FlowCompiler, FlowEngine, FlowPlan, FlowValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["flows"])


def _graph(project: Dict[str, Any], request: FlowRequest) -> Tuple[List[dict], List[dict]]:
    """
    The graph to compile, taken from the request when the client sent one.

    Autosave is debounced, so the canvas on screen is routinely a little ahead of
    the copy we have stored. Compile the stored one and the user watches the node
    they just connected get left out of the run.
    """
    if request.nodes is not None:
        return request.nodes, request.edges or []

    canvas = project.get("canvas_state") or {}
    return canvas.get("nodes") or [], canvas.get("edges") or []


def _require_owned_seeds(
    plan: FlowPlan,
    project_id: str,
    user_id: str,
    database: Database,
) -> None:
    """
    Check that every artifact the canvas seeds the run with sits in this project.

    The nodes come from the client, so a seed id is really a request to go and read
    some stored artifact. `SourceResolver` fetches those ids by id alone and never
    asks who owns them, which makes this the last place a flow naming someone
    else's artifact can be refused. Fixing the same hole in `create_job` did
    nothing for this route, because the canvas is a second door to the same code,
    and the saved canvas is a third one: `canvas_state` is caller-written through
    `PATCH`.

    A single bad seed fails the whole request. We don't drop the offending node and
    carry on, because a flow that quietly ran without one of its inputs still hands
    back confident-looking output, just built from the wrong material.
    """
    for node_id, artifact_id in plan.seed_artifacts.items():
        try:
            require_project_artifact(artifact_id, project_id, user_id, database)
        except HTTPException as error:
            raise HTTPException(
                status_code=error.status_code,
                detail=f"Node '{node_id}': {error.detail}",
            ) from error


@router.post("/{project_id}/flow/validate", response_model=FlowPlanResponse)
def validate_flow(
    project_id: str,
    request: FlowRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> FlowPlanResponse:
    """Compile the graph and report the plan, or say why it won't run."""
    project = require_project(project_id, user_id, database)
    nodes, edges = _graph(project, request)

    try:
        plan = FlowCompiler().compile(nodes, edges)
    except FlowValidationError as error:
        return FlowPlanResponse(valid=False, error=str(error))

    _require_owned_seeds(plan, project_id, user_id, database)

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
        plan = FlowCompiler().compile(nodes, edges)
    except FlowValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    _require_owned_seeds(plan, project_id, user_id, database)
    run = FlowEngine(database).start(project_id, nodes, edges, dispatch=enqueue)

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

    Live updates come over the WebSocket. This endpoint is for the client that has
    just reconnected: it can read where the run stands now and carry on from there,
    without us replaying every event it slept through.
    """
    require_project(project_id, user_id, database)

    run = FlowEngine(database).get(flow_run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})
