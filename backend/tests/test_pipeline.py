"""
End-to-end pipeline tests.

These run the real handlers against a real (temporary) database with the offline
LLM provider, so they cover the parts that unit tests of individual services miss:
transaction boundaries, provenance edges, chaining between artifact types, and
the retry classification that decides whether a failed job comes back.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from backend.handlers.generate_handler import GenerateHandler, SourceResolutionError
from backend.handlers.refine_handler import RefineHandler
from backend.models.jobs import JobModel
from backend.services.job_runner import JobExecutor, is_transient


def make_job(project_id: str, job_type: str, payload: dict, db) -> JobModel:
    """Insert a job and claim it, the way a worker would."""
    row = db.insert("jobs", {
        "project_id": project_id, "type": job_type, "status": "pending", "payload": payload,
    })[0]
    return db.claim_job(row["id"])


# --- generation ------------------------------------------------------------

class TestGeneration:
    @pytest.mark.parametrize(
        "target",
        ["quiz", "flashcards", "notes", "slides", "study_guide", "cheatsheet", "mindmap"],
    )
    def test_every_artifact_type_generates_and_commits(self, db, project, knowledge_core, target):
        job = make_job(project["id"], "generate", {
            "target_type": target, "source_artifact_ids": [knowledge_core["id"]],
        }, db)

        committed = asyncio.run(JobExecutor(db).execute(job))
        assert committed, f"{target} generation did not commit"

        artifacts = db.select("artifacts", [("project_id", f"eq.{project['id']}"), ("type", f"eq.{target}")])
        assert len(artifacts) == 1
        assert artifacts[0]["content"]["data"], "artifact has no payload"

        finished = db.get_job(job.id)
        assert finished["status"] == "completed"
        assert finished["result"]["artifact_type"] == target

    def test_multi_input_records_one_edge_per_source(self, db, project, knowledge_core):
        """Provenance must survive fan-in: three sources, three edges."""
        extra = [
            db.insert("artifacts", {
                "project_id": project["id"],
                "type": "knowledge_core",
                "content": {"kind": "core", "core": {
                    **knowledge_core["content"]["core"], "title": f"Source {index}",
                }},
            })[0]
            for index in range(2)
        ]
        source_ids = [knowledge_core["id"]] + [a["id"] for a in extra]

        job = make_job(project["id"], "generate", {
            "target_type": "notes", "source_artifact_ids": source_ids,
        }, db)
        assert asyncio.run(JobExecutor(db).execute(job))

        notes = db.select("artifacts", [("project_id", f"eq.{project['id']}"), ("type", "eq.notes")])[0]
        edges = db.get_all_parent_edges(notes["id"])
        assert sorted(e["parent_artifact_id"] for e in edges) == sorted(source_ids)

    def test_duplicate_sources_collapse_to_one_edge(self, db, project, knowledge_core):
        handler = GenerateHandler(db=db)
        ids = handler._source_ids({
            "source_artifact_ids": [knowledge_core["id"], knowledge_core["id"]],
        })
        assert ids == [knowledge_core["id"]]

    def test_chaining_uses_the_chained_artifact_not_its_ancestor(self, db, project, knowledge_core):
        """notes -> quiz must read the notes, not silently regenerate from the core."""
        notes_job = make_job(project["id"], "generate", {
            "target_type": "notes", "source_artifact_ids": [knowledge_core["id"]],
        }, db)
        assert asyncio.run(JobExecutor(db).execute(notes_job))
        notes = db.select("artifacts", [("type", "eq.notes"), ("project_id", f"eq.{project['id']}")])[0]

        handler = GenerateHandler(db=db)
        cores = handler.resolve_sources([notes["id"]], "quiz")
        assert len(cores) == 1
        assert notes["content"]["data"]["body"][:80] in cores[0].summary

    def test_unknown_target_type_is_rejected(self, db, project, knowledge_core):
        job = make_job(project["id"], "generate", {
            "target_type": "horoscope", "source_artifact_ids": [knowledge_core["id"]],
        }, db)

        assert not asyncio.run(JobExecutor(db).execute(job))
        assert db.get_job(job.id)["status"] == "failed"

    def test_missing_source_fails_the_job_cleanly(self, db, project):
        job = make_job(project["id"], "generate", {
            "target_type": "quiz", "source_artifact_ids": [str(uuid.uuid4())],
        }, db)

        assert not asyncio.run(JobExecutor(db).execute(job))
        failed = db.get_job(job.id)
        assert failed["status"] == "failed"
        assert "not found" in failed["error_message"].lower()

    def test_generation_is_steerable(self, db, project, knowledge_core):
        job = make_job(project["id"], "generate", {
            "target_type": "quiz",
            "source_artifact_ids": [knowledge_core["id"]],
            "instructions": "focus only on quorums",
        }, db)
        assert asyncio.run(JobExecutor(db).execute(job))

        quiz = db.select("artifacts", [("type", "eq.quiz"), ("project_id", f"eq.{project['id']}")])[0]
        assert quiz["content"]["instructions"] == "focus only on quorums"


# --- refinement ------------------------------------------------------------

class TestRefinement:
    def test_refine_creates_a_new_artifact_linked_to_the_old_one(self, db, project, knowledge_core):
        generate = make_job(project["id"], "generate", {
            "target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]],
        }, db)
        assert asyncio.run(JobExecutor(db).execute(generate))
        original = db.select("artifacts", [("type", "eq.quiz"), ("project_id", f"eq.{project['id']}")])[0]

        refine = make_job(project["id"], "refine", {
            "source_artifact_id": original["id"], "instructions": "make the questions harder",
        }, db)
        assert asyncio.run(JobExecutor(db).execute(refine))

        quizzes = db.select("artifacts", [("type", "eq.quiz"), ("project_id", f"eq.{project['id']}")])
        assert len(quizzes) == 2, "refinement should append a version, not overwrite one"

        revised = next(q for q in quizzes if q["id"] != original["id"])
        assert revised["content"]["refined_from"] == original["id"]
        assert db.get_all_parent_edges(revised["id"])[0]["parent_artifact_id"] == original["id"]

    def test_refine_without_instructions_is_rejected(self, db, project, knowledge_core):
        artifact = db.insert("artifacts", {
            "project_id": project["id"], "type": "quiz",
            "content": {"kind": "generated", "data": {"title": "Q", "questions": []}},
        })[0]

        job = make_job(project["id"], "refine", {"source_artifact_id": artifact["id"], "instructions": ""}, db)
        assert not asyncio.run(JobExecutor(db).execute(job))
        assert "instructions is required" in db.get_job(job.id)["error_message"]


# --- retry classification --------------------------------------------------

class TestRetryPolicy:
    @pytest.mark.parametrize("message", [
        "HTTP 429: rate limit exceeded",
        "Read timed out",
        "503 Service Unavailable",
        "upstream is overloaded",
    ])
    def test_transient_failures_are_retried(self, message):
        assert is_transient(RuntimeError(message))

    @pytest.mark.parametrize("message", [
        "target_type is required",
        "Source artifacts not found: abc",
        "quiz: expected at least 5 questions, got 2",
    ])
    def test_permanent_failures_are_not_retried(self, message):
        assert not is_transient(ValueError(message))

    def test_transient_failure_requeues_until_attempts_run_out(self, db, project, monkeypatch):
        """A rate-limited job goes back on the queue instead of dying."""
        monkeypatch.setenv("JOB_MAX_ATTEMPTS", "2")
        from backend.core.config import get_settings

        get_settings.cache_clear()

        job = make_job(project["id"], "generate", {"target_type": "quiz"}, db)
        assert db.fail_job(job.id, "HTTP 429: rate limit", retryable=True) == "pending"
        assert db.get_job(job.id)["status"] == "pending"

        db.claim_job(job.id)  # attempt 2
        assert db.fail_job(job.id, "HTTP 429: rate limit", retryable=True) == "failed"


# --- job queue semantics ---------------------------------------------------

class TestQueue:
    def test_a_job_is_claimed_exactly_once(self, db, project):
        """The claim has to be atomic or two workers duplicate the work."""
        row = db.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]

        first = db.claim_job()
        second = db.claim_job()

        assert first is not None and str(first.id) == row["id"]
        assert second is None

    def test_stale_running_jobs_are_returned_to_the_queue(self, db, project):
        """Without the reaper, a crashed worker strands its job forever."""
        row = db.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]
        db.claim_job(row["id"])
        assert db.get_job(row["id"])["status"] == "running"

        assert db.reap_stale_jobs(older_than_seconds=-1) == [row["id"]]
        assert db.get_job(row["id"])["status"] == "pending"

    def test_a_committed_job_cannot_be_committed_twice(self, db, project, knowledge_core):
        """Job history is append-only; a replayed commit must be refused."""
        from backend.models.protocol import JobBundle

        job = make_job(project["id"], "generate", {
            "target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]],
        }, db)
        assert asyncio.run(JobExecutor(db).execute(job))

        with pytest.raises(ValueError, match="already completed"):
            db.commit_bundle(JobBundle(job_id=job.id, project_id=project["id"], result={}))

    def test_cancelling_a_pending_job_takes_it_off_the_queue(self, db, project):
        row = db.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]

        assert db.cancel_job(row["id"]) is True
        assert db.claim_job() is None
        assert db.cancel_job(row["id"]) is False, "a cancelled job cannot be cancelled again"
