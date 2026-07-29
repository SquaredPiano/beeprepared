"""Flow compilation and scheduling: fan-in, fan-out, ordering and rejection."""

from __future__ import annotations

import pytest

from backend.services.flow import FlowCompiler, FlowEngine, FlowValidationError


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


class TestCompile:
    def test_linear_chain_is_ordered_by_depth(self):
        plan = FlowCompiler().compile(
            [source_node("s1", "a1"), generator_node("g1", "notes"), generator_node("g2", "quiz")],
            [edge("s1", "g1"), edge("g1", "g2")],
        )
        by_node = {step.node_id: step for step in plan.steps}
        assert by_node["g1"].depth < by_node["g2"].depth
        assert by_node["g2"].parents == ["g1"]

    def test_fan_in_gives_a_step_every_parent(self):
        """Two lectures into one set of notes: both must reach the generator."""
        plan = FlowCompiler().compile(
            [source_node("s1", "a1"), source_node("s2", "a2"), generator_node("g1", "notes")],
            [edge("s1", "g1"), edge("s2", "g1")],
        )
        assert sorted(plan.steps[0].parents) == ["s1", "s2"]

    def test_fan_out_gives_every_child_the_same_parent(self):
        """One quiz into flashcards, an exam and a cheat sheet, all at the same depth."""
        plan = FlowCompiler().compile(
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
        plan = FlowCompiler().compile(
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
        plan = FlowCompiler().compile(
            [source_node("s1", "a1"), generator_node("g1", "quiz")],
            [edge("s1", "g1"), edge("s1", "g1")],
        )
        assert plan.steps[0].parents == ["s1"]

    def test_dangling_edges_from_deleted_nodes_are_ignored(self):
        plan = FlowCompiler().compile(
            [source_node("s1", "a1"), generator_node("g1", "quiz")],
            [edge("s1", "g1"), edge("ghost", "g1"), edge("g1", "ghost")],
        )
        assert plan.steps[0].parents == ["s1"]

    def test_instructions_travel_with_the_node(self):
        plan = FlowCompiler().compile(
            [source_node("s1", "a1"), generator_node("g1", "quiz", "focus on chapter 3")],
            [edge("s1", "g1")],
        )
        assert plan.steps[0].instructions == "focus on chapter 3"


class TestValidation:
    def test_cycle_is_rejected(self):
        with pytest.raises(FlowValidationError, match="cycle"):
            FlowCompiler().compile(
                [source_node("s1", "a1"), generator_node("g1", "quiz"), generator_node("g2", "notes")],
                [edge("s1", "g1"), edge("g1", "g2"), edge("g2", "g1")],
            )

    def test_self_loop_is_rejected(self):
        with pytest.raises(FlowValidationError, match="itself"):
            FlowCompiler().compile(
                [source_node("s1", "a1"), generator_node("g1", "quiz")],
                [edge("s1", "g1"), edge("g1", "g1")],
            )

    def test_generator_without_input_is_rejected(self):
        with pytest.raises(FlowValidationError, match="no input"):
            FlowCompiler().compile(
                [source_node("s1", "a1"), generator_node("g1", "quiz"), generator_node("g2", "notes")],
                [edge("s1", "g1")],
            )

    def test_generator_without_output_type_is_rejected(self):
        with pytest.raises(FlowValidationError, match="no output type"):
            FlowCompiler().compile(
                [source_node("s1", "a1"), {"id": "g1", "type": "generator", "data": {"label": "?"}}],
                [edge("s1", "g1")],
            )

    def test_canvas_with_no_generators_is_rejected(self):
        with pytest.raises(FlowValidationError, match="Nothing to run"):
            FlowCompiler().compile([source_node("s1", "a1")], [])

    def test_empty_canvas_is_rejected(self):
        with pytest.raises(FlowValidationError, match="empty"):
            FlowCompiler().compile([], [])

    def test_a_canvas_past_the_node_limit_is_rejected(self):
        """
        The canvas is request data, so its size is the caller's to choose.

        Compilation walks every node and every edge, and the run that follows
        queues one job per generator. With no limit, a single request buys an
        unbounded amount of work.
        """
        from backend.services.flow.plan import MAX_NODES

        oversized = [source_node(f"s{index}", "a1") for index in range(MAX_NODES + 1)]

        with pytest.raises(FlowValidationError, match=f"limited to {MAX_NODES} nodes"):
            FlowCompiler().compile(oversized, [])


class TestScheduling:
    def test_only_the_first_wave_is_dispatched_initially(self, database, project, knowledge_core):
        """A downstream node must not be queued before its input exists."""
        dispatched: list[str] = []
        engine = FlowEngine(database)

        run = engine.start(
            project["id"],
            [source_node("s1", knowledge_core["id"]), generator_node("g1", "quiz"), generator_node("g2", "flashcards")],
            [edge("s1", "g1"), edge("g1", "g2")],
            dispatch=dispatched.append,
        )

        assert len(dispatched) == 1
        assert run["node_states"]["g1"]["status"] == "running"
        assert run["node_states"]["g2"]["status"] == "pending"

    def test_completion_unblocks_the_next_wave_with_the_new_artifact(self, database, project, knowledge_core):
        dispatched: list[str] = []
        engine = FlowEngine(database)

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

    def test_fan_in_node_waits_for_every_parent(self, database, project, knowledge_core):
        dispatched: list[str] = []
        engine = FlowEngine(database)

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

    def test_failure_skips_everything_downstream(self, database, project, knowledge_core):
        engine = FlowEngine(database)
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

    def test_a_step_with_no_usable_input_still_reaches_a_terminal_state(
        self, database, project, knowledge_core
    ):
        """A parent that finished with no artifact must not leave the run stuck running."""
        engine = FlowEngine(database)
        engine.start(
            project["id"],
            [
                source_node("s1", knowledge_core["id"]),
                generator_node("g1", "notes"),
                generator_node("g2", "quiz"),
                generator_node("g3", "flashcards"),
            ],
            [edge("s1", "g1"), edge("g1", "g2"), edge("g2", "g3")],
            dispatch=lambda _: None,
        )
        run_id = engine.list_for_project(project["id"])[0]["id"]

        engine.on_job_finished(run_id, "g1", artifact_id=None)

        run = engine.get(run_id)
        assert run["node_states"]["g2"]["status"] == "failed"
        assert run["node_states"]["g3"]["status"] == "skipped"
        assert run["status"] == "failed"

    def test_run_completes_when_every_step_lands(self, database, project, knowledge_core):
        engine = FlowEngine(database)
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

    def test_advance_is_idempotent(self, database, project, knowledge_core):
        """
        A second sequential advance finds no pending step and dispatches nothing.

        This pins the `status != "pending"` guard and nothing beyond it. The two
        calls run one after the other on a single thread, so an engine with no
        transaction around the read-then-write passes this quite happily. For the
        concurrent case, where two advances interleave inside that window, see
        `TestFlowConcurrency::test_concurrent_completions_queue_the_next_step_once`
        in backend/tests/test_pipeline.py.
        """
        dispatched: list[str] = []
        engine = FlowEngine(database)
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
