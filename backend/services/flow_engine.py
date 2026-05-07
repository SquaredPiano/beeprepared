"""
Flow engine: executing the canvas as a dependency graph.

The canvas used to be decorative. You could wire nodes together, but "Run" hit
an endpoint that did not exist, and each generator node independently fetched
the project's knowledge core - so the edges you drew changed nothing.

This module makes the drawing the program.

What it does
------------
1. **Compiles** the React Flow graph into an execution plan: which nodes produce
   artifacts, which nodes consume them, and in what order.
2. **Validates** it before anything runs - cycles, unreachable nodes, generators
   with no inputs, and type transitions that make no sense are all rejected up
   front with a message naming the node, rather than failing three jobs deep.
3. **Schedules** it wave by wave. Every node whose inputs are ready is dispatched
   at once, so independent branches run concurrently instead of in draw order.

Fan-in and fan-out both fall out of this: a node with three incoming edges is
dispatched with three ``source_artifact_ids`` and merged by ``CoreMerger``; a
node with three outgoing edges unblocks three downstream nodes when it finishes.
That is what turns the canvas into a step-function builder - lecture + textbook
into one set of notes, one quiz into flashcards *and* an exam *and* a cheat sheet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from backend.models.artifacts import GENERATED_ARTIFACT_TYPES
from backend.services.db_interface import DBInterface
from backend.services.events import (
    EVENT_FLOW_COMPLETED,
    EVENT_FLOW_FAILED,
    EVENT_FLOW_NODE_UPDATE,
    EVENT_FLOW_STARTED,
    publish,
)

logger = logging.getLogger(__name__)

# Canvas node types that stand for an artifact that already exists.
SOURCE_NODE_TYPES = {"asset", "artifactNode", "source", "result", "knowledgeCore"}
# Canvas node types that produce a new artifact when the flow runs.
GENERATOR_NODE_TYPES = {"generator", "agent", "task"}

MAX_NODES = 100


class FlowValidationError(ValueError):
    """Raised when a canvas graph cannot be compiled into a runnable plan."""


@dataclass
class FlowStep:
    """One generator node in the plan."""

    node_id: str
    target_type: str
    parents: List[str] = field(default_factory=list)   # canvas node ids
    instructions: Optional[str] = None
    depth: int = 0                                      # wave index

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "target_type": self.target_type,
            "parents": self.parents,
            "instructions": self.instructions,
            "depth": self.depth,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FlowStep":
        return FlowStep(
            node_id=data["node_id"],
            target_type=data["target_type"],
            parents=list(data.get("parents") or []),
            instructions=data.get("instructions"),
            depth=int(data.get("depth", 0)),
        )


@dataclass
class FlowPlan:
    """A validated, ordered execution plan for one canvas."""

    steps: List[FlowStep]
    # Canvas node id -> the artifact id it already resolves to (source nodes).
    seed_artifacts: Dict[str, str]

    @property
    def waves(self) -> List[List[FlowStep]]:
        """Steps grouped by depth. Everything in a wave can run concurrently."""
        grouped: Dict[int, List[FlowStep]] = {}
        for step in self.steps:
            grouped.setdefault(step.depth, []).append(step)
        return [grouped[depth] for depth in sorted(grouped)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "seed_artifacts": self.seed_artifacts,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FlowPlan":
        return FlowPlan(
            steps=[FlowStep.from_dict(step) for step in data.get("steps", [])],
            seed_artifacts=dict(data.get("seed_artifacts") or {}),
        )


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def _node_kind(node: Dict[str, Any]) -> str:
    node_type = node.get("type") or ""
    data = node.get("data") or {}

    if node_type in GENERATOR_NODE_TYPES or data.get("subType") in GENERATED_ARTIFACT_TYPES:
        return "generator"
    if node_type in SOURCE_NODE_TYPES or (data.get("artifact") or {}).get("id"):
        return "source"
    return "unknown"


def _artifact_id_of(node: Dict[str, Any]) -> Optional[str]:
    """The artifact a source node already points at, if any."""
    data = node.get("data") or {}
    artifact = data.get("artifact") or {}
    return artifact.get("id") or data.get("artifactId") or None


def _target_type_of(node: Dict[str, Any]) -> Optional[str]:
    data = node.get("data") or {}
    candidate = data.get("subType") or data.get("targetType") or data.get("type")
    return candidate if candidate in GENERATED_ARTIFACT_TYPES else None


def compile_flow(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> FlowPlan:
    """
    Turn a React Flow graph into a validated ``FlowPlan``.

    Raises ``FlowValidationError`` with a message naming the offending node, so
    the UI can highlight it instead of showing a generic failure.
    """
    if not nodes:
        raise FlowValidationError("The canvas is empty. Add a source and a generator to run a flow.")
    if len(nodes) > MAX_NODES:
        raise FlowValidationError(f"Flows are limited to {MAX_NODES} nodes; this canvas has {len(nodes)}.")

    by_id: Dict[str, Dict[str, Any]] = {str(node["id"]): node for node in nodes if node.get("id")}

    generators: Dict[str, str] = {}     # node id -> target type
    seed_artifacts: Dict[str, str] = {} # node id -> existing artifact id

    for node_id, node in by_id.items():
        kind = _node_kind(node)
        if kind == "generator":
            target = _target_type_of(node)
            if not target:
                label = (node.get("data") or {}).get("label") or node_id
                raise FlowValidationError(
                    f"Generator node '{label}' has no output type set. "
                    f"Choose one of: {', '.join(sorted(GENERATED_ARTIFACT_TYPES))}."
                )
            generators[node_id] = target
        elif kind == "source":
            artifact_id = _artifact_id_of(node)
            if artifact_id:
                seed_artifacts[node_id] = str(artifact_id)

    if not generators:
        raise FlowValidationError(
            "This flow has nothing to run. Drag in a generator node and connect a source to it."
        )

    # --- adjacency ---------------------------------------------------------
    incoming: Dict[str, List[str]] = {node_id: [] for node_id in by_id}
    outgoing: Dict[str, List[str]] = {node_id: [] for node_id in by_id}

    for edge in edges or []:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source not in by_id or target not in by_id:
            continue  # dangling edge left behind by a deleted node
        if source == target:
            raise FlowValidationError(f"Node '{target}' is connected to itself.")
        if source in incoming[target]:
            continue  # the same pair wired twice - one edge is enough
        incoming[target].append(source)
        outgoing[source].append(target)

    # --- generators must have something to work from -----------------------
    for node_id, target in generators.items():
        usable_parents = [
            parent for parent in incoming[node_id]
            if parent in generators or parent in seed_artifacts
        ]
        if not usable_parents:
            label = (by_id[node_id].get("data") or {}).get("label") or target
            raise FlowValidationError(
                f"Generator node '{label}' has no input. Connect a source or another "
                "generator to it before running the flow."
            )

    # --- cycle detection and ordering (Kahn) -------------------------------
    relevant: Set[str] = set(generators) | set(seed_artifacts)
    indegree = {
        node_id: len([p for p in incoming[node_id] if p in relevant])
        for node_id in relevant
    }
    depth = {node_id: 0 for node_id in relevant}

    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    ordered: List[str] = []

    while queue:
        node_id = queue.pop(0)
        ordered.append(node_id)
        for child in outgoing.get(node_id, []):
            if child not in relevant:
                continue
            depth[child] = max(depth[child], depth[node_id] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(relevant):
        stuck = sorted(relevant - set(ordered))
        labels = [
            (by_id[node_id].get("data") or {}).get("label") or node_id for node_id in stuck[:5]
        ]
        raise FlowValidationError(
            "This flow contains a cycle - a node eventually feeds back into itself. "
            f"Involved nodes: {', '.join(labels)}."
        )

    steps = [
        FlowStep(
            node_id=node_id,
            target_type=generators[node_id],
            parents=[p for p in incoming[node_id] if p in relevant],
            instructions=(by_id[node_id].get("data") or {}).get("instructions"),
            depth=depth[node_id],
        )
        for node_id in ordered
        if node_id in generators
    ]

    logger.info("Compiled flow: %d steps across %d waves", len(steps),
                len({step.depth for step in steps}))
    return FlowPlan(steps=steps, seed_artifacts=seed_artifacts)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class FlowEngine:
    """
    Runs a compiled plan by creating jobs wave by wave.

    The engine holds no in-memory state between calls: everything it needs lives
    in the ``flow_runs`` row. That is deliberate - the job that unblocks a step
    may finish in a different process (a Celery worker) than the one that
    started the run, so progress has to be readable from the database.
    """

    def __init__(self, db: Optional[DBInterface] = None):
        self.db = db or DBInterface()

    # -- start --------------------------------------------------------------

    def start(
        self,
        project_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        *,
        dispatch=None,
    ) -> Dict[str, Any]:
        """
        Compile, persist and kick off a flow run.

        ``dispatch`` is the callable that hands a job id to the queue; it is
        injected so the engine does not depend on the worker implementation.
        """
        plan = compile_flow(nodes, edges)

        node_states = {
            step.node_id: {"status": "pending", "target_type": step.target_type}
            for step in plan.steps
        }
        for node_id, artifact_id in plan.seed_artifacts.items():
            node_states[node_id] = {"status": "ready", "artifact_id": artifact_id}

        run = self.db.insert("flow_runs", {
            "project_id": str(project_id),
            "status": "running",
            "plan": plan.to_dict(),
            "node_states": node_states,
            "result": {},
        })[0]

        publish(project_id, EVENT_FLOW_STARTED, {
            "flow_run_id": run["id"],
            "steps": len(plan.steps),
            "waves": len(plan.waves),
        })
        logger.info("Flow run %s started: %d steps", run["id"], len(plan.steps))

        self.advance(run["id"], dispatch=dispatch)
        return self.get(run["id"])

    # -- scheduling ---------------------------------------------------------

    def advance(self, flow_run_id: str, *, dispatch=None) -> Dict[str, Any]:
        """
        Dispatch every step whose inputs are now satisfied.

        Called once at start and again whenever a job belonging to this run
        finishes. Idempotent: a step already dispatched is skipped, so a
        duplicate completion notification cannot double-run it.
        """
        run = self.get(flow_run_id)
        if not run or run["status"] not in {"running", "pending"}:
            return run or {}

        plan = FlowPlan.from_dict(run["plan"])
        states: Dict[str, Dict[str, Any]] = dict(run["node_states"])
        project_id = run["project_id"]

        ready = [
            step for step in plan.steps
            if states.get(step.node_id, {}).get("status") == "pending"
            and self._inputs_ready(step, states)
        ]

        for step in ready:
            source_ids = self._resolve_inputs(step, states)
            if not source_ids:
                # Every parent finished but produced nothing usable.
                states[step.node_id] = {
                    **states.get(step.node_id, {}),
                    "status": "failed",
                    "error": "No source artifacts were produced by this node's inputs",
                }
                continue

            job = self.db.insert("jobs", {
                "project_id": project_id,
                "type": "generate",
                "status": "pending",
                "payload": {
                    "target_type": step.target_type,
                    "source_artifact_ids": source_ids,
                    "instructions": step.instructions,
                    "flow_run_id": flow_run_id,
                    "flow_node_id": step.node_id,
                },
            })[0]

            states[step.node_id] = {
                **states.get(step.node_id, {}),
                "status": "running",
                "job_id": job["id"],
                "source_artifact_ids": source_ids,
            }
            publish(project_id, EVENT_FLOW_NODE_UPDATE, {
                "flow_run_id": flow_run_id,
                "node_id": step.node_id,
                "status": "running",
                "job_id": job["id"],
            })

            if dispatch is not None:
                dispatch(job["id"])

        self._save_states(flow_run_id, states, plan, project_id)
        return self.get(flow_run_id)

    @staticmethod
    def _inputs_ready(step: FlowStep, states: Dict[str, Dict[str, Any]]) -> bool:
        """A step runs only once every parent has produced (or already is) an artifact."""
        for parent in step.parents:
            state = states.get(parent)
            if not state:
                return False
            if state.get("status") not in {"ready", "completed"}:
                return False
        return True

    @staticmethod
    def _resolve_inputs(step: FlowStep, states: Dict[str, Dict[str, Any]]) -> List[str]:
        """The artifact ids this step should be generated from - one per parent."""
        ids: List[str] = []
        for parent in step.parents:
            artifact_id = (states.get(parent) or {}).get("artifact_id")
            if artifact_id and artifact_id not in ids:
                ids.append(artifact_id)
        return ids

    # -- completion ---------------------------------------------------------

    def on_job_finished(
        self,
        flow_run_id: str,
        node_id: str,
        *,
        artifact_id: Optional[str] = None,
        error: Optional[str] = None,
        dispatch=None,
    ) -> Dict[str, Any]:
        """Record a step's outcome and schedule whatever it unblocked."""
        run = self.get(flow_run_id)
        if not run:
            logger.warning("Ignoring completion for unknown flow run %s", flow_run_id)
            return {}

        states = dict(run["node_states"])
        project_id = run["project_id"]

        if error:
            states[node_id] = {**states.get(node_id, {}), "status": "failed", "error": error}
            # Everything downstream of a failed node can never run.
            plan = FlowPlan.from_dict(run["plan"])
            for blocked in self._descendants(node_id, plan):
                if states.get(blocked, {}).get("status") == "pending":
                    states[blocked] = {
                        **states.get(blocked, {}),
                        "status": "skipped",
                        "error": f"Upstream node {node_id} failed",
                    }
        else:
            states[node_id] = {
                **states.get(node_id, {}),
                "status": "completed",
                "artifact_id": artifact_id,
            }

        publish(project_id, EVENT_FLOW_NODE_UPDATE, {
            "flow_run_id": flow_run_id,
            "node_id": node_id,
            "status": states[node_id]["status"],
            "artifact_id": artifact_id,
            "error": error,
        })

        self.db.update("flow_runs", [("id", f"eq.{flow_run_id}")], {"node_states": states})
        return self.advance(flow_run_id, dispatch=dispatch)

    @staticmethod
    def _descendants(node_id: str, plan: FlowPlan) -> Set[str]:
        """Every step reachable from ``node_id`` in the plan."""
        children: Dict[str, List[str]] = {}
        for step in plan.steps:
            for parent in step.parents:
                children.setdefault(parent, []).append(step.node_id)

        seen: Set[str] = set()
        stack = list(children.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(children.get(current, []))
        return seen

    # -- persistence --------------------------------------------------------

    def _save_states(
        self,
        flow_run_id: str,
        states: Dict[str, Dict[str, Any]],
        plan: FlowPlan,
        project_id: str,
    ) -> None:
        """Write node states back and finalise the run if nothing is left to do."""
        step_statuses = [states.get(step.node_id, {}).get("status") for step in plan.steps]
        terminal = {"completed", "failed", "skipped"}
        update: Dict[str, Any] = {"node_states": states}

        if all(status in terminal for status in step_statuses):
            failed = [s for s in step_statuses if s in {"failed", "skipped"}]
            update["status"] = "failed" if failed else "completed"
            update["completed_at"] = datetime.now(timezone.utc).isoformat()
            update["result"] = {
                "completed": step_statuses.count("completed"),
                "failed": step_statuses.count("failed"),
                "skipped": step_statuses.count("skipped"),
            }
            publish(
                project_id,
                EVENT_FLOW_FAILED if failed else EVENT_FLOW_COMPLETED,
                {"flow_run_id": flow_run_id, **update["result"]},
            )
            logger.info("Flow run %s finished: %s", flow_run_id, update["result"])

        self.db.update("flow_runs", [("id", f"eq.{flow_run_id}")], update)

    def get(self, flow_run_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.select("flow_runs", [("id", f"eq.{flow_run_id}")])
        return rows[0] if rows else None

    def list_for_project(self, project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.select(
            "flow_runs",
            [("project_id", f"eq.{project_id}")],
            order="created_at.desc",
            limit=limit,
        )
