"""Compiles a canvas graph into a validated, ordered execution plan."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.models.artifacts import GENERATED_TYPES

logger = logging.getLogger(__name__)

SOURCE_NODE_TYPES = frozenset({"asset", "artifactNode", "source", "result", "knowledgeCore"})
GENERATOR_NODE_TYPES = frozenset({"generator", "agent", "task"})
MAX_NODES = 100


class FlowValidationError(ValueError):
    """A canvas graph cannot be turned into a runnable plan."""


@dataclass
class FlowStep:
    """One generator node, and what has to finish before it can run."""

    node_id: str
    target_type: str
    parents: List[str] = field(default_factory=list)
    instructions: Optional[str] = None
    depth: int = 0

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
    """A validated execution plan for one canvas."""

    steps: List[FlowStep]
    seed_artifacts: Dict[str, str]

    @property
    def waves(self) -> List[List[FlowStep]]:
        """Steps grouped by depth. Everything in a wave can run at once."""
        grouped: Dict[int, List[FlowStep]] = {}
        for step in self.steps:
            grouped.setdefault(step.depth, []).append(step)
        return [grouped[depth] for depth in sorted(grouped)]

    def descendants_of(self, node_id: str) -> Set[str]:
        """Every step reachable from `node_id`."""
        children: Dict[str, List[str]] = {}
        for step in self.steps:
            for parent in step.parents:
                children.setdefault(parent, []).append(step.node_id)

        found: Set[str] = set()
        pending = list(children.get(node_id, []))
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current)
                pending.extend(children.get(current, []))
        return found

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


class FlowCompiler:
    """
    Turns React Flow nodes and edges into a `FlowPlan`.

    Every rejection names the offending node, so the canvas can point at the
    problem before any work is dispatched.
    """

    def compile(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> FlowPlan:
        """Validate the graph and return its execution plan."""
        if not nodes:
            raise FlowValidationError("The canvas is empty. Add a source and a generator to run.")
        if len(nodes) > MAX_NODES:
            raise FlowValidationError(f"Flows are limited to {MAX_NODES} nodes; this has {len(nodes)}.")

        by_id = {str(node["id"]): node for node in nodes if node.get("id")}
        generators, seeds = self._classify(by_id)

        if not generators:
            raise FlowValidationError(
                "Nothing to run. Drag in a generator node and connect a source to it."
            )

        incoming, outgoing = self._adjacency(by_id, edges)
        runnable = set(generators) | set(seeds)
        self._require_inputs(generators, incoming, runnable, by_id)

        order, depth = self._topological_order(runnable, incoming, outgoing, by_id)

        steps = [
            FlowStep(
                node_id=node_id,
                target_type=generators[node_id],
                parents=[parent for parent in incoming[node_id] if parent in runnable],
                instructions=(by_id[node_id].get("data") or {}).get("instructions"),
                depth=depth[node_id],
            )
            for node_id in order
            if node_id in generators
        ]

        logger.info("Compiled %d steps across %d waves", len(steps), len({s.depth for s in steps}))
        return FlowPlan(steps=steps, seed_artifacts=seeds)

    def _classify(self, by_id: Dict[str, Dict[str, Any]]) -> tuple[Dict[str, str], Dict[str, str]]:
        generators: Dict[str, str] = {}
        seeds: Dict[str, str] = {}

        for node_id, node in by_id.items():
            if self._is_generator(node):
                target = self._target_type(node)
                if not target:
                    label = (node.get("data") or {}).get("label") or node_id
                    raise FlowValidationError(
                        f"Generator '{label}' has no output type. "
                        f"Choose one of: {', '.join(sorted(GENERATED_TYPES))}."
                    )
                generators[node_id] = target
            elif self._is_source(node):
                artifact_id = self._artifact_id(node)
                if artifact_id:
                    seeds[node_id] = artifact_id

        return generators, seeds

    @staticmethod
    def _adjacency(
        by_id: Dict[str, Dict[str, Any]],
        edges: List[Dict[str, Any]],
    ) -> tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        incoming: Dict[str, List[str]] = {node_id: [] for node_id in by_id}
        outgoing: Dict[str, List[str]] = {node_id: [] for node_id in by_id}

        for edge in edges or []:
            source, target = str(edge.get("source")), str(edge.get("target"))
            if source not in by_id or target not in by_id:
                continue
            if source == target:
                raise FlowValidationError(f"Node '{target}' is connected to itself.")
            if source in incoming[target]:
                continue
            incoming[target].append(source)
            outgoing[source].append(target)

        return incoming, outgoing

    @staticmethod
    def _require_inputs(
        generators: Dict[str, str],
        incoming: Dict[str, List[str]],
        runnable: Set[str],
        by_id: Dict[str, Dict[str, Any]],
    ) -> None:
        for node_id, target in generators.items():
            if not any(parent in runnable for parent in incoming[node_id]):
                label = (by_id[node_id].get("data") or {}).get("label") or target
                raise FlowValidationError(
                    f"Generator '{label}' has no input. Connect a source or another "
                    "generator to it before running."
                )

    @staticmethod
    def _topological_order(
        runnable: Set[str],
        incoming: Dict[str, List[str]],
        outgoing: Dict[str, List[str]],
        by_id: Dict[str, Dict[str, Any]],
    ) -> tuple[List[str], Dict[str, int]]:
        indegree = {
            node_id: len([p for p in incoming[node_id] if p in runnable])
            for node_id in runnable
        }
        depth = {node_id: 0 for node_id in runnable}
        queue = [node_id for node_id, count in indegree.items() if count == 0]
        order: List[str] = []

        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
            for child in outgoing.get(node_id, []):
                if child not in runnable:
                    continue
                depth[child] = max(depth[child], depth[node_id] + 1)
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(runnable):
            stuck = sorted(runnable - set(order))
            labels = [(by_id[node_id].get("data") or {}).get("label") or node_id for node_id in stuck[:5]]
            raise FlowValidationError(
                "This flow contains a cycle: a node eventually feeds back into itself. "
                f"Involved: {', '.join(labels)}."
            )

        return order, depth

    @staticmethod
    def _is_generator(node: Dict[str, Any]) -> bool:
        data = node.get("data") or {}
        return node.get("type") in GENERATOR_NODE_TYPES or data.get("subType") in GENERATED_TYPES

    @staticmethod
    def _is_source(node: Dict[str, Any]) -> bool:
        data = node.get("data") or {}
        return node.get("type") in SOURCE_NODE_TYPES or bool((data.get("artifact") or {}).get("id"))

    @staticmethod
    def _artifact_id(node: Dict[str, Any]) -> Optional[str]:
        data = node.get("data") or {}
        artifact = data.get("artifact") or {}
        found = artifact.get("id") or data.get("artifactId")
        return str(found) if found else None

    @staticmethod
    def _target_type(node: Dict[str, Any]) -> Optional[str]:
        data = node.get("data") or {}
        candidate = data.get("subType") or data.get("targetType") or data.get("type")
        return candidate if candidate in GENERATED_TYPES else None
