"""
Shared test fixtures.

Every test runs against a throwaway SQLite database, a throwaway storage
directory and the offline LLM provider. That means the suite exercises the real
handlers, the real transaction boundaries and the real DAG traversal without
touching a network or spending a token - so it can run in CI, on a plane, and on
a laptop whose API keys expired months ago.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Point every process-wide singleton at a fresh, empty world."""
    monkeypatch.setenv("BEE_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LLM_PROVIDER", "offline")
    monkeypatch.setenv("STORAGE_SIGNING_SECRET", "test-secret")
    monkeypatch.setenv("WORKER_CONCURRENCY", "2")
    monkeypatch.setenv("CELERY_ENABLED", "false")
    for name in ("SUPABASE_URL", "SUPABASE_KEY", "REDIS_URL",
                 "OPENROUTER_API_KEY", "GEMINI_API_KEY", "VERTEX_PROJECT_ID"):
        monkeypatch.setenv(name, "")

    from backend.core.config import get_settings
    from backend.core.services.llm_factory import LLMFactory
    from backend.services import db_interface, dispatcher, events, local_db, storage

    # These are all deliberately cached per process; reset them so one test's
    # configuration cannot leak into the next.
    get_settings.cache_clear()
    LLMFactory.reset()
    db_interface.reset_backend()
    local_db.reset_local_db()
    storage.reset_object_store()
    events.reset_event_bus()
    dispatcher.reset()

    yield

    get_settings.cache_clear()
    LLMFactory.reset()
    db_interface.reset_backend()
    local_db.reset_local_db()
    storage.reset_object_store()
    events.reset_event_bus()
    dispatcher.reset()


@pytest.fixture
def db():
    from backend.services.db_interface import DBInterface

    return DBInterface()


@pytest.fixture
def project(db):
    """A project owned by the local user."""
    from backend.api.deps import LOCAL_USER_ID

    return db.insert("projects", {
        "name": "Test Project",
        "description": "fixture",
        "user_id": LOCAL_USER_ID,
        "canvas_state": {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []},
    })[0]


@pytest.fixture
def knowledge_core(db, project):
    """A ready-to-use knowledge core artifact, as ingest would have produced."""
    return db.insert("artifacts", {
        "project_id": project["id"],
        "type": "knowledge_core",
        "content": {
            "kind": "core",
            "core": {
                "title": "Distributed Systems",
                "summary": (
                    "Consensus protocols let a set of unreliable machines agree on a single "
                    "value. Paxos and Raft are the canonical algorithms. Raft separates "
                    "leader election from log replication to make the protocol teachable. "
                    "A quorum is a majority of nodes, which guarantees any two quorums "
                    "intersect in at least one node."
                ),
                "concepts": [
                    {"name": "Consensus", "description": "Agreement among unreliable nodes", "importance_score": 10},
                    {"name": "Quorum", "description": "A majority subset of nodes", "importance_score": 8},
                    {"name": "Raft", "description": "An understandable consensus algorithm", "importance_score": 9},
                ],
                "section_hierarchy": [
                    {"title": "Consensus", "summary": "Why agreement is hard", "subsections": []}
                ],
                "notes": [{"heading": "Core ideas", "bullets": ["Quorums intersect", "Leaders simplify replication"]}],
                "definitions": [{"term": "Quorum", "definition": "A majority of nodes", "context": "Consensus"}],
                "examples": [{"description": "Raft leader election", "relevance": "Shows term-based voting"}],
                "key_facts": [{"fact": "Any two majority quorums intersect", "category": "Technical"}],
            },
        },
    })[0]


@pytest.fixture
def client():
    """A FastAPI test client with the app's lifespan running."""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as test_client:
        test_client.headers.update({"Authorization": "Bearer mock-token"})
        yield test_client
