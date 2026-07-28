"""Fixtures giving every test a fresh database, file store and offline model."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLE_CORE: Dict[str, Any] = {
    "title": "Distributed Systems",
    "summary": (
        "Consensus protocols let unreliable machines agree on a single value. "
        "A quorum is a majority of nodes, so any two quorums intersect. Raft "
        "separates leader election from log replication to stay teachable."
    ),
    "concepts": [
        {"name": "Consensus", "description": "Agreement among unreliable nodes", "importance_score": 10},
        {"name": "Quorum", "description": "A majority subset of nodes", "importance_score": 8},
        {"name": "Raft", "description": "An understandable consensus algorithm", "importance_score": 9},
    ],
    "section_hierarchy": [
        {"title": "Consensus", "summary": "Why agreement is hard", "subsections": []}
    ],
    "notes": [
        {"heading": "Core ideas", "bullets": ["Quorums intersect", "Leaders simplify replication"]}
    ],
    "definitions": [
        {"term": "Quorum", "definition": "A majority of nodes", "context": "Consensus"}
    ],
    "examples": [
        {"description": "Raft leader election", "relevance": "Shows term-based voting"}
    ],
    "key_facts": [
        {"fact": "Any two majority quorums intersect", "category": "Technical"}
    ],
}


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """
    Point every shared singleton at an empty world.

    Settings, the model provider, the database, the file store, the event bus
    and the dispatcher are all cached per process by design, so each has to be
    reset or one test's configuration leaks into the next.
    """
    monkeypatch.setenv("BEE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("CELERY_ENABLED", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("REDIS_URL", "")

    _reset_singletons()
    yield
    _reset_singletons()


def _reset_singletons() -> None:
    from backend.core.config import get_settings
    from backend.llm import factory
    from backend.services import database, dispatcher, events, files

    get_settings.cache_clear()
    factory.reset_provider()
    database.reset_database()
    files.reset_file_store()
    events.reset_event_bus()
    dispatcher.reset()


@pytest.fixture
def database():
    from backend.services.database import get_database

    return get_database()


@pytest.fixture
def project(database):
    from backend.api.deps import LOCAL_USER_ID

    return database.insert("projects", {
        "name": "Test Project",
        "description": "fixture",
        "user_id": LOCAL_USER_ID,
    })[0]


@pytest.fixture
def knowledge_core(database, project):
    """A knowledge core artifact, as ingest would have produced."""
    return database.insert("artifacts", {
        "project_id": project["id"],
        "type": "knowledge_core",
        "content": {"kind": "core", "core": SAMPLE_CORE},
    })[0]


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def idle_client(monkeypatch):
    """
    A client whose lifespan starts no workers.

    The pool drains the queue in the background, so anything asserted about a
    freshly queued job races it: the row's status, and for an upload the staged
    copy the ingest handler releases as its last act. Turning the pool off makes
    the precondition a fact rather than a question of scheduling.
    """
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import job_runner

    async def start_nothing(pool) -> None:
        return None

    monkeypatch.setattr(job_runner.WorkerPool, "start", start_nothing)

    with TestClient(app) as test_client:
        yield test_client
