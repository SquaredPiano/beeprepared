"""End-to-end pipeline behaviour, run against a real database and the offline model."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.handlers.generate_handler import GenerateHandler
from backend.handlers.sources import SourceResolver
from backend.models.graph import JobBundle
from backend.models.jobs import JobModel
from backend.services.job_runner import JobExecutor, is_transient


def queue(database, project_id: str, job_type: str, payload: dict) -> JobModel:
    """Insert a job and claim it, the way a worker would."""
    row = database.insert("jobs", {
        "project_id": project_id, "type": job_type, "status": "pending", "payload": payload,
    })[0]
    return database.claim_job(row["id"])


def run(database, project_id: str, job_type: str, payload: dict) -> tuple[bool, JobModel]:
    """Queue a job and execute it, returning whether it committed."""
    job = queue(database, project_id, job_type, payload)
    return asyncio.run(JobExecutor(database).execute(job)), job


class TestGeneration:
    @pytest.mark.parametrize(
        "target",
        ["quiz", "flashcards", "notes", "slides", "study_guide", "cheatsheet", "mindmap"],
    )
    def test_every_artifact_type_generates_and_commits(self, database, project, knowledge_core, target):
        committed, job = run(database, project["id"], "generate", {
            "target_type": target, "source_artifact_ids": [knowledge_core["id"]],
        })
        assert committed, f"{target} did not commit"

        artifacts = database.select(
            "artifacts", [("project_id", f"eq.{project['id']}"), ("type", f"eq.{target}")]
        )
        assert len(artifacts) == 1
        assert artifacts[0]["content"]["data"]

        finished = database.get_job(job.id)
        assert finished["status"] == "completed"
        assert finished["result"]["artifact_type"] == target

    def test_multi_input_records_one_edge_per_source(self, database, project, knowledge_core):
        """Provenance survives fan-in: three sources produce three edges."""
        extra = [
            database.insert("artifacts", {
                "project_id": project["id"],
                "type": "knowledge_core",
                "content": {"kind": "core", "core": {
                    **knowledge_core["content"]["core"], "title": f"Source {index}",
                }},
            })[0]
            for index in range(2)
        ]
        sources = [knowledge_core["id"]] + [artifact["id"] for artifact in extra]

        committed, _ = run(database, project["id"], "generate", {
            "target_type": "notes", "source_artifact_ids": sources,
        })
        assert committed

        notes = database.select(
            "artifacts", [("project_id", f"eq.{project['id']}"), ("type", "eq.notes")]
        )[0]
        edges = database.get_parent_edges(notes["id"])
        assert sorted(edge["parent_artifact_id"] for edge in edges) == sorted(sources)

    def test_duplicate_sources_collapse_to_one_edge(self, knowledge_core):
        handler = GenerateHandler()
        assert handler._unique([knowledge_core["id"], knowledge_core["id"]]) == [knowledge_core["id"]]

    def test_chaining_reads_the_chained_artifact_not_its_ancestor(self, database, project, knowledge_core):
        """notes into quiz must read the notes, not regenerate from the core."""
        committed, _ = run(database, project["id"], "generate", {
            "target_type": "notes", "source_artifact_ids": [knowledge_core["id"]],
        })
        assert committed

        notes = database.select(
            "artifacts", [("type", "eq.notes"), ("project_id", f"eq.{project['id']}")]
        )[0]

        cores = SourceResolver(database).resolve([notes["id"]], "quiz")
        assert len(cores) == 1
        assert notes["content"]["data"]["body"][:80] in cores[0].summary

    def test_unknown_target_type_fails_the_job(self, database, project, knowledge_core):
        committed, job = run(database, project["id"], "generate", {
            "target_type": "horoscope", "source_artifact_ids": [knowledge_core["id"]],
        })
        assert not committed
        assert database.get_job(job.id)["status"] == "failed"

    def test_missing_source_fails_with_a_clear_message(self, database, project):
        committed, job = run(database, project["id"], "generate", {
            "target_type": "quiz", "source_artifact_ids": [str(uuid.uuid4())],
        })
        assert not committed

        failed = database.get_job(job.id)
        assert failed["status"] == "failed"
        assert "not found" in failed["error_message"].lower()

    def test_generation_is_steerable(self, database, project, knowledge_core):
        committed, _ = run(database, project["id"], "generate", {
            "target_type": "quiz",
            "source_artifact_ids": [knowledge_core["id"]],
            "instructions": "focus only on quorums",
        })
        assert committed

        quiz = database.select(
            "artifacts", [("type", "eq.quiz"), ("project_id", f"eq.{project['id']}")]
        )[0]
        assert quiz["content"]["instructions"] == "focus only on quorums"


class TestRefinement:
    def test_refine_appends_a_version_linked_to_the_original(self, database, project, knowledge_core):
        run(database, project["id"], "generate", {
            "target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]],
        })
        original = database.select(
            "artifacts", [("type", "eq.quiz"), ("project_id", f"eq.{project['id']}")]
        )[0]

        committed, _ = run(database, project["id"], "refine", {
            "source_artifact_id": original["id"], "instructions": "make the questions harder",
        })
        assert committed

        quizzes = database.select(
            "artifacts", [("type", "eq.quiz"), ("project_id", f"eq.{project['id']}")]
        )
        assert len(quizzes) == 2, "refinement should append, not overwrite"

        revised = next(quiz for quiz in quizzes if quiz["id"] != original["id"])
        assert revised["content"]["refined_from"] == original["id"]
        assert database.get_parent_edges(revised["id"])[0]["parent_artifact_id"] == original["id"]

    def test_refine_without_instructions_is_rejected(self, database, project):
        artifact = database.insert("artifacts", {
            "project_id": project["id"],
            "type": "quiz",
            "content": {"kind": "generated", "data": {"title": "Q", "questions": []}},
        })[0]

        committed, job = run(database, project["id"], "refine", {
            "source_artifact_id": artifact["id"], "instructions": "   ",
        })
        assert not committed
        assert "instructions is required" in database.get_job(job.id)["error_message"]


class TestRetryPolicy:
    @pytest.mark.parametrize("message", [
        "HTTP 429: rate limit exceeded",
        "Read timed out",
        "503 Service Unavailable",
        "upstream is overloaded",
    ])
    def test_transient_failures_retry(self, message):
        assert is_transient(RuntimeError(message))

    @pytest.mark.parametrize("message", [
        "target_type is required",
        "Source artifacts not found: abc",
        "Expected at least 5 questions, got 2",
    ])
    def test_permanent_failures_do_not_retry(self, message):
        assert not is_transient(ValueError(message))

    @pytest.mark.parametrize("identifier", [
        "429e4567-e89b-12d3-a456-426614174000",
        "Source artifacts not found: 502",
        "artifact 504 has no content",
    ])
    def test_status_digits_inside_identifiers_do_not_trigger_a_retry(self, identifier):
        """A bare three-digit match would retry anything containing those digits."""
        assert not is_transient(ValueError(f"Source artifacts not found: {identifier}"))

    def test_a_transient_failure_requeues_until_attempts_run_out(self, database, project, monkeypatch):
        monkeypatch.setenv("JOB_MAX_ATTEMPTS", "2")
        from backend.core.config import get_settings

        get_settings.cache_clear()

        job = queue(database, project["id"], "generate", {"target_type": "quiz"})
        assert database.fail_job(job.id, "HTTP 429: rate limit", retryable=True) == "pending"
        assert database.get_job(job.id)["status"] == "pending"

        database.claim_job(job.id)
        assert database.fail_job(job.id, "HTTP 429: rate limit", retryable=True) == "failed"


class TestQueue:
    def test_a_job_is_claimed_exactly_once(self, database, project):
        """Without an atomic claim, two workers run the same job."""
        row = database.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]

        first, second = database.claim_job(), database.claim_job()

        assert first is not None and str(first.id) == row["id"]
        assert second is None

    def test_stale_running_jobs_return_to_the_queue(self, database, project):
        """Without the reaper, a crashed worker strands its job forever."""
        row = database.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]
        database.claim_job(row["id"])
        assert database.get_job(row["id"])["status"] == "running"

        assert database.reap_stale_jobs(older_than_seconds=-1) == [row["id"]]
        assert database.get_job(row["id"])["status"] == "pending"

    def test_a_committed_job_cannot_commit_twice(self, database, project, knowledge_core):
        committed, job = run(database, project["id"], "generate", {
            "target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]],
        })
        assert committed

        with pytest.raises(ValueError, match="already completed"):
            database.commit_bundle(JobBundle(job_id=job.id, project_id=project["id"]))

    def test_cancelling_takes_a_job_off_the_queue(self, database, project):
        row = database.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]

        assert database.cancel_job(row["id"]) is True
        assert database.claim_job() is None
        assert database.cancel_job(row["id"]) is False
