"""Fixtures that hand every test a fresh database, file store and offline model."""

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
    Give every test an empty world to run in.

    Settings, the model provider, the database, the file store, the event bus and
    the dispatcher are all cached for the life of the process, which is what we
    want in production. Here it means one test's configuration leaks into the
    next one unless all six are reset.

    Clearing both API keys matters more than it looks. We load `.env` in tests
    too, so on a machine with real keys the suite would call Deepgram and
    OpenRouter for real, and it would behave differently from the same suite run
    where there are no keys at all.
    """
    monkeypatch.setenv("BEE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("CELERY_ENABLED", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("DEEPGRAM_KEY", "")
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
    """A knowledge core artifact, the way a finished ingest would have left it."""
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

    The pool drains the queue in the background, so a test that asserts anything
    about a job it just queued is racing it. The row's status is the obvious one,
    and for an upload there's also the staged copy that the ingest handler
    releases as its last act. With the pool off, that job is pending because
    nothing can claim it, not because nothing got round to it yet.
    """
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.services import job_runner

    async def start_nothing(pool) -> None:
        return None

    monkeypatch.setattr(job_runner.WorkerPool, "start", start_nothing)

    with TestClient(app) as test_client:
        yield test_client
