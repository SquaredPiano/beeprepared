"""
Flow compilation and scheduling.

These are the tests that matter most for the canvas feature: they pin down that
the graph the user draws is the graph that runs - fan-in, fan-out, ordering, and
the failure cases that should be caught before any tokens are spent.
"""

from __future__ import annotations

import pytest

from backend.services.flow_engine import FlowEngine, FlowValidationError, compile_flow


def source_node(node_id: str, artifact_id: str) -> dict:
    return {
        "id": node_id,
        "type": "artifactNode",
        "data": {"type": "knowledge_core", "artifact": {"id": artifact_id}},
    }


def generator_node(node_id: str, target: str, instructions: str | None = None) -> dict:
    return {
        "id": node_id,
        "type": "generator",
        "data": {"subType": target, "label": target, "instructions": instructions},
    }


def edge(source: str, target: str) -> dict:
    return {"id": f"e-{source}-{target}", "source": source, "target": target}


# --- compilation -----------------------------------------------------------

class TestCompile:
    def test_linear_chain_is_ordered_by_depth(self):
        plan = compile_flow(
            [source_node("s1", "a1"), generator_node("g1", "notes"), generator_node("g2", "quiz")],
            [edge("s1", "g1"), edge("g1", "g2")],
        )
        by_node = {step.node_id: step for step in plan.steps}
        assert by_node["g1"].depth < by_node["g2"].depth
        assert by_node["g2"].parents == ["g1"]

    def test_fan_in_gives_a_step_every_parent(self):
        """Two lectures into one set of notes: both must reach the generator."""
        plan = compile_flow(
            [source_node("s1", "a1"), source_node("s2", "a2"), generator_node("g1", "notes")],
            [edge("s1", "g1"), edge("s2", "g1")],
        )
        assert sorted(plan.steps[0].parents) == ["s1", "s2"]

    def test_fan_out_gives_every_child_the_same_parent(self):
        """One quiz into flashcards, an exam and a cheat sheet - all at one depth."""
        plan = compile_flow(
            [
                source_node("s1", "a1"),
                generator_node("g1", "quiz"),
                generator_node("g2", "flashcards"),
                generator_node("g3", "exam"),
                generator_node("g4", "cheatsheet"),
            ],
            [edge("s1", "g1"), edge("g1", "g2"), edge("g1", "g3"), edge("g1", "g4")],
        )
        downstream = [step for step in plan.steps if step.node_id != "g1"]
        assert len(downstream) == 3
        assert all(step.parents == ["g1"] for step in downstream)
        assert len({step.depth for step in downstream}) == 1, "siblings should run in one wave"

    def test_waves_group_independent_work(self):
        plan = compile_flow(
            [
                source_node("s1", "a1"),
                generator_node("g1", "notes"),
                generator_node("g2", "quiz"),
                generator_node("g3", "flashcards"),
            ],
            [edge("s1", "g1"), edge("s1", "g2"), edge("g2", "g3")],
        )
        waves = plan.waves
        assert len(waves) == 2
        assert {step.node_id for step in waves[0]} == {"g1", "g2"}

    def test_duplicate_edges_do_not_duplicate_parents(self):
        plan = compile_flow(
            [source_node("s1", "a1"), generator_node("g1", "quiz")],
            [edge("s1", "g1"), edge("s1", "g1")],
        )
        assert plan.steps[0].parents == ["s1"]

    def test_dangling_edges_from_deleted_nodes_are_ignored(self):
        plan = compile_flow(
            [source_node("s1", "a1"), generator_node("g1", "quiz")],
            [edge("s1", "g1"), edge("ghost", "g1"), edge("g1", "ghost")],
        )
        assert plan.steps[0].parents == ["s1"]

    def test_instructions_travel_with_the_node(self):
        plan = compile_flow(
            [source_node("s1", "a1"), generator_node("g1", "quiz", "focus on chapter 3")],
            [edge("s1", "g1")],
        )
        assert plan.steps[0].instructions == "focus on chapter 3"


# --- validation ------------------------------------------------------------

class TestValidation:
    def test_cycle_is_rejected(self):
        with pytest.raises(FlowValidationError, match="cycle"):
            compile_flow(
                [source_node("s1", "a1"), generator_node("g1", "quiz"), generator_node("g2", "notes")],
                [edge("s1", "g1"), edge("g1", "g2"), edge("g2", "g1")],
            )

    def test_self_loop_is_rejected(self):
        with pytest.raises(FlowValidationError, match="itself"):
            compile_flow(
                [source_node("s1", "a1"), generator_node("g1", "quiz")],
                [edge("s1", "g1"), edge("g1", "g1")],
            )

    def test_generator_without_input_is_rejected(self):
        with pytest.raises(FlowValidationError, match="no input"):
            compile_flow(
                [source_node("s1", "a1"), generator_node("g1", "quiz"), generator_node("g2", "notes")],
                [edge("s1", "g1")],
            )

    def test_generator_without_output_type_is_rejected(self):
        with pytest.raises(FlowValidationError, match="no output type"):
            compile_flow(
                [source_node("s1", "a1"), {"id": "g1", "type": "generator", "data": {"label": "?"}}],
                [edge("s1", "g1")],
            )

    def test_canvas_with_no_generators_is_rejected(self):
        with pytest.raises(FlowValidationError, match="nothing to run"):
            compile_flow([source_node("s1", "a1")], [])

    def test_empty_canvas_is_rejected(self):
        with pytest.raises(FlowValidationError, match="empty"):
            compile_flow([], [])


# --- scheduling ------------------------------------------------------------

class TestScheduling:
    def test_only_the_first_wave_is_dispatched_initially(self, db, project, knowledge_core):
        """A downstream node must not be queued before its input exists."""
        dispatched: list[str] = []
        engine = FlowEngine(db)

        run = engine.start(
            project["id"],
            [source_node("s1", knowledge_core["id"]), generator_node("g1", "quiz"), generator_node("g2", "flashcards")],
            [edge("s1", "g1"), edge("g1", "g2")],
            dispatch=dispatched.append,
        )

        assert len(dispatched) == 1
        assert run["node_states"]["g1"]["status"] == "running"
        assert run["node_states"]["g2"]["status"] == "pending"

    def test_completion_unblocks_the_next_wave_with_the_new_artifact(self, db, project, knowledge_core):
        dispatched: list[str] = []
        engine = FlowEngine(db)

        engine.start(
            project["id"],
            [source_node("s1", knowledge_core["id"]), generator_node("g1", "quiz"), generator_node("g2", "flashcards")],
            [edge("s1", "g1"), edge("g1", "g2")],
            dispatch=dispatched.append,
        )
        run_id = engine.list_for_project(project["id"])[0]["id"]

        engine.on_job_finished(run_id, "g1", artifact_id="quiz-artifact-1", dispatch=dispatched.append)

        run = engine.get(run_id)
        assert run["node_states"]["g2"]["status"] == "running"
        assert run["node_states"]["g2"]["source_artifact_ids"] == ["quiz-artifact-1"]
        assert len(dispatched) == 2

    def test_fan_in_node_waits_for_every_parent(self, db, project, knowledge_core):
        dispatched: list[str] = []
        engine = FlowEngine(db)

        engine.start(
            project["id"],
            [
                source_node("s1", knowledge_core["id"]),
                generator_node("g1", "notes"),
                generator_node("g2", "quiz"),
                generator_node("g3", "exam"),
            ],
            [edge("s1", "g1"), edge("s1", "g2"), edge("g1", "g3"), edge("g2", "g3")],
            dispatch=dispatched.append,
        )
        run_id = engine.list_for_project(project["id"])[0]["id"]

        engine.on_job_finished(run_id, "g1", artifact_id="notes-1", dispatch=dispatched.append)
        assert engine.get(run_id)["node_states"]["g3"]["status"] == "pending", "one parent is not enough"

        engine.on_job_finished(run_id, "g2", artifact_id="quiz-1", dispatch=dispatched.append)
        state = engine.get(run_id)["node_states"]["g3"]
        assert state["status"] == "running"
        assert sorted(state["source_artifact_ids"]) == ["notes-1", "quiz-1"]

    def test_failure_skips_everything_downstream(self, db, project, knowledge_core):
        engine = FlowEngine(db)
        engine.start(
            project["id"],
            [source_node("s1", knowledge_core["id"]), generator_node("g1", "quiz"), generator_node("g2", "flashcards")],
            [edge("s1", "g1"), edge("g1", "g2")],
            dispatch=lambda _: None,
        )
        run_id = engine.list_for_project(project["id"])[0]["id"]

        engine.on_job_finished(run_id, "g1", error="model refused")

        run = engine.get(run_id)
        assert run["node_states"]["g1"]["status"] == "failed"
        assert run["node_states"]["g2"]["status"] == "skipped"
        assert run["status"] == "failed"

    def test_run_completes_when_every_step_lands(self, db, project, knowledge_core):
        engine = FlowEngine(db)
        engine.start(
            project["id"],
            [source_node("s1", knowledge_core["id"]), generator_node("g1", "quiz")],
            [edge("s1", "g1")],
            dispatch=lambda _: None,
        )
        run_id = engine.list_for_project(project["id"])[0]["id"]

        engine.on_job_finished(run_id, "g1", artifact_id="quiz-1")

        run = engine.get(run_id)
        assert run["status"] == "completed"
        assert run["result"]["completed"] == 1

    def test_advance_is_idempotent(self, db, project, knowledge_core):
        """A duplicate completion notification must not run a step twice."""
        dispatched: list[str] = []
        engine = FlowEngine(db)
        engine.start(
            project["id"],
            [source_node("s1", knowledge_core["id"]), generator_node("g1", "quiz")],
            [edge("s1", "g1")],
            dispatch=dispatched.append,
        )
        run_id = engine.list_for_project(project["id"])[0]["id"]

        engine.advance(run_id, dispatch=dispatched.append)
        engine.advance(run_id, dispatch=dispatched.append)

        assert len(dispatched) == 1
