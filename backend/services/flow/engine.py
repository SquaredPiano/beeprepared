"""Runs a compiled canvas plan, a wave of independent steps at a time."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.services.database import Database, get_database
from backend.services.events import (
    FLOW_COMPLETED,
    FLOW_FAILED,
    FLOW_NODE,
    FLOW_STARTED,
    publish,
)
from backend.services.flow.plan import FlowCompiler, FlowPlan, FlowStep

logger = logging.getLogger(__name__)

Dispatch = Callable[[str], Any]

READY_STATUSES = frozenset({"ready", "completed"})
FINISHED_STATUSES = frozenset({"completed", "failed", "skipped"})


class EventOutbox:
    """
    Sits on flow events until the transaction that produced them has committed.

    Publish from inside an open transaction and you've announced a node the
    database hasn't stored yet. If the commit fails, or anything later in the
    block raises, the write rolls back and the user is left looking at a green
    node that never ran. There's a second reason to wait: delivery is a blocking
    round trip to Redis, and sitting on that call while we hold the write lock
    holds up every other writer.
    """

    def __init__(self) -> None:
        self._pending: List[Tuple[str, str, Dict[str, Any]]] = []

    def record(self, project_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Hold on to an event until the row it talks about is really there."""
        self._pending.append((project_id, event_type, data))

    def flush(self) -> None:
        """Send everything we were holding, in the order it happened."""
        for project_id, event_type, data in self._pending:
            publish(project_id, event_type, data)
        self._pending.clear()


class FlowEngine:
    """
    Dispatches the steps of a flow as their inputs turn up.

    We keep nothing in memory between calls. The job that unblocks a step can
    finish in a different process from the one that started the run, so all the
    progress lives in the `flow_runs` row and we read it back every time.
    """

    def __init__(
        self,
        database: Optional[Database] = None,
        compiler: Optional[FlowCompiler] = None,
    ) -> None:
        self._database = database or get_database()
        self._compiler = compiler or FlowCompiler()

    def start(
        self,
        project_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        *,
        dispatch: Optional[Dispatch] = None,
    ) -> Dict[str, Any]:
        """Compile the graph, write the run down, then kick off the first wave."""
        plan = self._compiler.compile(nodes, edges)

        states: Dict[str, Dict[str, Any]] = {
            step.node_id: {"status": "pending", "target_type": step.target_type}
            for step in plan.steps
        }
        for node_id, artifact_id in plan.seed_artifacts.items():
            states[node_id] = {"status": "ready", "artifact_id": artifact_id}

        run = self._database.insert("flow_runs", {
            "project_id": str(project_id),
            "status": "running",
            "plan": plan.to_dict(),
            "node_states": states,
            "result": {},
        })[0]

        publish(project_id, FLOW_STARTED, {
            "flow_run_id": run["id"],
            "steps": len(plan.steps),
            "waves": len(plan.waves),
        })
        logger.info("Flow run %s started with %d steps", run["id"], len(plan.steps))

        self.advance(run["id"], dispatch=dispatch)
        return self.get(run["id"]) or run

    def advance(self, flow_run_id: str, *, dispatch: Optional[Dispatch] = None) -> Dict[str, Any]:
        """
        Queue up every step whose inputs have arrived.

        Calling this twice is safe. Reading a step's state, inserting its job row
        and marking it running all happen inside one transaction, so a repeated
        completion notice, or two of them landing at once, can't start the same
        step twice.

        Events, the dispatch calls and the row we hand back all wait for the
        commit. That way nobody hears about progress the database went on to roll
        back.
        """
        outbox = EventOutbox()

        with self._database.transaction():
            queued = self._schedule(flow_run_id, outbox)

        outbox.flush()
        self._hand_off(queued, dispatch)
        return self.get(flow_run_id) or {}

    def _schedule(self, flow_run_id: str, outbox: EventOutbox) -> List[str]:
        """
        Queue the steps that are ready and return their job ids.

        The caller opens the transaction, not us, because the read of
        `node_states` and every write that follows from it have to land together.
        """
        run = self.get(flow_run_id)
        if not run or run["status"] != "running":
            return []

        plan = FlowPlan.from_dict(run["plan"])
        states = dict(run["node_states"])
        project_id = run["project_id"]
        queued: List[str] = []

        for step in plan.steps:
            if states.get(step.node_id, {}).get("status") != "pending":
                continue
            if not self._inputs_ready(step, states):
                continue

            sources = self._input_artifacts(step, states)
            if not sources:
                reason = "This node's inputs produced no artifacts"
                states[step.node_id] = {
                    **states.get(step.node_id, {}),
                    "status": "failed",
                    "error": reason,
                }
                self._skip_downstream(step.node_id, plan, states)
                outbox.record(project_id, FLOW_NODE, {
                    "flow_run_id": flow_run_id,
                    "node_id": step.node_id,
                    "status": "failed",
                    "error": reason,
                })
                continue

            job = self._queue_job(project_id, flow_run_id, step, sources)
            states[step.node_id] = {
                **states.get(step.node_id, {}),
                "status": "running",
                "job_id": job["id"],
                "source_artifact_ids": sources,
            }
            outbox.record(project_id, FLOW_NODE, {
                "flow_run_id": flow_run_id,
                "node_id": step.node_id,
                "status": "running",
                "job_id": job["id"],
            })
            queued.append(job["id"])

        self._save(flow_run_id, project_id, plan, states, outbox)
        return queued

    @staticmethod
    def _hand_off(job_ids: List[str], dispatch: Optional[Dispatch]) -> None:
        """Tell the workers about the jobs, now that their rows are committed."""
        if not dispatch:
            return
        for job_id in job_ids:
            dispatch(job_id)

    def on_job_finished(
        self,
        flow_run_id: str,
        node_id: str,
        *,
        artifact_id: Optional[str] = None,
        error: Optional[str] = None,
        dispatch: Optional[Dispatch] = None,
    ) -> Dict[str, Any]:
        """
        Write down what a step produced, then schedule whatever it unblocked.

        The read of `node_states`, the change we make to it, the write back and
        the scheduling that follows all sit inside one transaction. Two things
        break if they don't. When both parents of a fan-in step finish at the same
        moment, each write clobbers the other's completion, and the step below
        them waits forever on a parent the row no longer remembers. Overlapping
        callers can also each see the same step as pending and each queue it. We
        measured that one before the transaction went in: eight concurrent
        completions produced nine dispatched jobs.

        Events, the dispatch calls and the row we hand back all wait for the
        commit. Before the events moved out here, a rollback could leave the
        browser showing a node as finished that the database said had never run.
        """
        outbox = EventOutbox()

        with self._database.transaction():
            run = self.get(flow_run_id)
            if not run:
                logger.warning("Completion for unknown flow run %s", flow_run_id)
                return {}

            states = dict(run["node_states"])
            project_id = run["project_id"]

            if error:
                states[node_id] = {**states.get(node_id, {}), "status": "failed", "error": error}
                self._skip_downstream(node_id, FlowPlan.from_dict(run["plan"]), states)
            else:
                states[node_id] = {
                    **states.get(node_id, {}),
                    "status": "completed",
                    "artifact_id": artifact_id,
                }

            outbox.record(project_id, FLOW_NODE, {
                "flow_run_id": flow_run_id,
                "node_id": node_id,
                "status": states[node_id]["status"],
                "artifact_id": artifact_id,
                "error": error,
            })

            self._database.update(
                "flow_runs", [("id", f"eq.{flow_run_id}")], {"node_states": states}
            )
            queued = self._schedule(flow_run_id, outbox)

        outbox.flush()
        self._hand_off(queued, dispatch)
        return self.get(flow_run_id) or {}

    def get(self, flow_run_id: str) -> Optional[Dict[str, Any]]:
        rows = self._database.select("flow_runs", [("id", f"eq.{flow_run_id}")])
        return rows[0] if rows else None

    def list_for_project(self, project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self._database.select(
            "flow_runs",
            [("project_id", f"eq.{project_id}")],
            order="created_at.desc",
            limit=limit,
        )

    def _queue_job(
        self,
        project_id: str,
        flow_run_id: str,
        step: FlowStep,
        sources: List[str],
    ) -> Dict[str, Any]:
        return self._database.insert("jobs", {
            "project_id": project_id,
            "type": "generate",
            "status": "pending",
            "payload": {
                "target_type": step.target_type,
                "source_artifact_ids": sources,
                "instructions": step.instructions,
                "flow_run_id": flow_run_id,
                "flow_node_id": step.node_id,
            },
        })[0]

    @staticmethod
    def _inputs_ready(step: FlowStep, states: Dict[str, Dict[str, Any]]) -> bool:
        return all(
            (states.get(parent) or {}).get("status") in READY_STATUSES
            for parent in step.parents
        )

    @staticmethod
    def _input_artifacts(step: FlowStep, states: Dict[str, Dict[str, Any]]) -> List[str]:
        found: List[str] = []
        for parent in step.parents:
            artifact_id = (states.get(parent) or {}).get("artifact_id")
            if artifact_id and artifact_id not in found:
                found.append(artifact_id)
        return found

    @staticmethod
    def _skip_downstream(node_id: str, plan: FlowPlan, states: Dict[str, Dict[str, Any]]) -> None:
        """
        Mark everything below a failed node as skipped.

        If we left those steps pending they'd never run and never finish, and the
        run itself would sit at "running" forever waiting on them.
        """
        for blocked in plan.descendants_of(node_id):
            if states.get(blocked, {}).get("status") == "pending":
                states[blocked] = {
                    **states.get(blocked, {}),
                    "status": "skipped",
                    "error": f"Upstream node {node_id} failed",
                }

    def _save(
        self,
        flow_run_id: str,
        project_id: str,
        plan: FlowPlan,
        states: Dict[str, Dict[str, Any]],
        outbox: EventOutbox,
    ) -> None:
        update: Dict[str, Any] = {"node_states": states}
        statuses = [states.get(step.node_id, {}).get("status") for step in plan.steps]

        if all(status in FINISHED_STATUSES for status in statuses):
            tally = {
                "completed": statuses.count("completed"),
                "failed": statuses.count("failed"),
                "skipped": statuses.count("skipped"),
            }
            failed = tally["failed"] + tally["skipped"] > 0

            update["status"] = "failed" if failed else "completed"
            update["completed_at"] = datetime.now(timezone.utc).isoformat()
            update["result"] = tally

            outbox.record(project_id, FLOW_FAILED if failed else FLOW_COMPLETED,
                          {"flow_run_id": flow_run_id, **tally})
            logger.info("Flow run %s finished: %s", flow_run_id, tally)

        self._database.update("flow_runs", [("id", f"eq.{flow_run_id}")], update)
