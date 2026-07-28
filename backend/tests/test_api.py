"""HTTP and WebSocket surface: the contract, ownership rules and the event stream."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend.models.artifacts import GENERATED_TYPES, SOURCE_TYPES


def create_project(client, name="API Project") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def idle_client(monkeypatch):
    """
    A client whose lifespan starts no workers.

    The pool drains the queue in the background, so anything asserted about a
    freshly queued job races it: the row's status, and for an upload the staged
    file the ingest handler deletes as its last act. Turning the pool off makes
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


class TestMeta:
    def test_health_reports_what_it_is_wired_to(self, client):
        """Every fixture forces CELERY_ENABLED=false, so there is one right answer."""
        body = client.get("/health").json()
        assert body["status"] == "healthy"
        assert body["model"] == "offline"
        assert body["jobs"] == "local"

    def test_capabilities_lists_every_artifact_type(self, client):
        """The canvas builds its palette from this, so a short list is a missing feature."""
        body = client.get("/api/capabilities").json()
        assert set(body["artifact_types"]) == set(GENERATED_TYPES)
        assert set(body["source_types"]) == set(SOURCE_TYPES)
        assert body["features"]["flows"] is True


class TestProjects:
    def test_create_read_update_delete(self, client):
        project = create_project(client)
        project_id = project["id"]

        assert client.get(f"/api/projects/{project_id}").json()["name"] == "API Project"

        canvas = {"viewport": {"x": 1, "y": 2, "zoom": 1.5}, "nodes": [{"id": "n1"}], "edges": []}
        updated = client.patch(f"/api/projects/{project_id}", json={"name": "Renamed", "canvas_state": canvas})
        assert updated.status_code == 200
        assert updated.json()["name"] == "Renamed"
        assert updated.json()["canvas_state"]["viewport"]["zoom"] == 1.5

        assert client.delete(f"/api/projects/{project_id}").status_code == 200
        assert client.get(f"/api/projects/{project_id}").status_code == 404

    def test_empty_update_is_rejected(self, client):
        project = create_project(client)
        assert client.patch(f"/api/projects/{project['id']}", json={}).status_code == 400

    def test_another_users_project_is_not_visible(self, client, database):
        """Ownership is enforced on read, not only on write."""
        foreign = database.insert("projects", {"name": "Not yours", "user_id": "someone-else"})[0]
        assert client.get(f"/api/projects/{foreign['id']}").status_code == 403
        assert foreign["id"] not in [p["id"] for p in client.get("/api/projects").json()]

    def test_missing_project_is_a_404_not_a_500(self, client):
        assert client.get("/api/projects/00000000-0000-0000-0000-000000000000").status_code == 404


class TestUploads:
    def test_upload_queues_an_ingest_job(self, idle_client, database):
        """
        202 is a promise about a row, so the row is what has to be right.

        The queued job is the only description of the upload that outlives the
        request: its source type, the name the file arrived under, and a
        `source_ref` naming the staged bytes the ingest handler will read.

        Nothing runs that handler here, so the staged copy it would have deleted
        is this test's to remove.
        """
        project = create_project(idle_client)
        uploaded = b"# Lecture\n\nConsensus is hard." * 20

        response = idle_client.post(
            f"/api/projects/{project['id']}/upload",
            files={"file": ("lecture.md", io.BytesIO(uploaded), "text/markdown")},
            data={"source_type": "md"},
        )
        assert response.status_code == 202, response.text

        job = database.get_job(response.json()["job_id"])
        assert job["type"] == "ingest"
        assert job["status"] == "pending"
        assert job["payload"]["source_type"] == "md"
        assert job["payload"]["original_name"] == "lecture.md"

        staged = Path(job["payload"]["source_ref"])
        assert staged.read_bytes() == uploaded
        staged.unlink()

    def test_unknown_source_type_is_rejected(self, client):
        project = create_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/upload",
            files={"file": ("x.exe", io.BytesIO(b"binary"), "application/octet-stream")},
            data={"source_type": "executable"},
        )
        assert response.status_code == 400

    def test_empty_upload_is_rejected(self, client):
        project = create_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/upload",
            files={"file": ("empty.md", io.BytesIO(b""), "text/markdown")},
            data={"source_type": "md"},
        )
        assert response.status_code == 400

    def test_oversized_upload_is_rejected(self, client, monkeypatch):
        monkeypatch.setenv("MAX_FILE_SIZE_MB", "1")
        from backend.core.config import get_settings

        get_settings.cache_clear()

        project = create_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/upload",
            files={"file": ("big.md", io.BytesIO(b"x" * (2 * 1024 * 1024)), "text/markdown")},
            data={"source_type": "md"},
        )
        assert response.status_code == 413


class TestJobs:
    def test_create_and_read_a_generate_job(self, idle_client, database, knowledge_core, project):
        """
        The read is the stored row, not a fixed shape.

        The browser polls this endpoint to decide whether a node is still
        spinning and what it was asked to make, so the id, the project, the
        live status and the payload all have to come back off the row.
        """
        payload = {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]}

        response = idle_client.post("/api/jobs", json={
            "project_id": project["id"], "type": "generate", "payload": payload,
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        status = idle_client.get(f"/api/jobs/{job_id}")
        assert status.status_code == 200

        body = status.json()
        assert body["id"] == job_id
        assert body["project_id"] == project["id"]
        assert body["type"] == "generate"
        assert body["status"] == "pending"
        assert body["payload"] == payload

        database.claim_job(job_id)
        assert idle_client.get(f"/api/jobs/{job_id}").json()["status"] == "running"

    def test_a_generate_request_naming_no_source_is_refused(self, client, database, project):
        """Generation reads from the graph, so a request naming nothing is not work."""
        response = client.post("/api/jobs", json={
            "project_id": project["id"], "type": "generate", "payload": {"target_type": "quiz"},
        })

        assert response.status_code == 400, response.text
        assert "at least one artifact" in response.json()["detail"]
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_an_unknown_ingest_source_type_is_refused(self, client, database, project):
        """
        The upload route has its own check; this door reaches the model instead.

        `POST /api/jobs` builds an `IngestRequest` from the payload and never
        looks at the source type itself, so the only thing standing between a
        made-up type and a queued job is the validator on the model.
        """
        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "ingest",
            "payload": {
                "source_type": "executable",
                "source_ref": "/tmp/lecture.exe",
                "original_name": "lecture.exe",
            },
        })

        assert response.status_code == 400, response.text
        assert "source_type must be one of" in response.json()["detail"]
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_invalid_target_type_is_a_400_with_a_useful_message(self, client, project, knowledge_core):
        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "horoscope", "source_artifact_ids": [knowledge_core["id"]]},
        })
        assert response.status_code == 400
        assert "target_type must be one of" in response.json()["detail"]

    def test_identical_in_flight_requests_are_deduplicated(
        self, idle_client, database, project, knowledge_core
    ):
        """
        The second request must join the first rather than queue a second run.

        The precondition is that the first job is still in flight, and with a
        live worker pool draining the queue that is a matter of timing: the run
        this asserts about can finish between the two posts. `idle_client`
        starts no workers, so the first job is pending because nothing can
        claim it, not because nothing happened to.
        """
        payload = {
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]},
        }
        first = idle_client.post("/api/jobs", json=payload).json()
        assert database.get_job(first["job_id"])["status"] == "pending"

        second = idle_client.post("/api/jobs", json=payload).json()

        assert second["reused"] is True
        assert second["job_id"] == first["job_id"]
        assert len(database.select("jobs", [("project_id", f"eq.{project['id']}")])) == 1

    def test_a_completed_job_is_never_handed_back_to_a_later_request(
        self, idle_client, database, project, knowledge_core
    ):
        """
        Regenerate is a request for new work, not a lookup of the old result.

        Counting finished jobs as duplicates made the button look broken: the
        API answered with the previous artifact's job, nothing ran, and the
        canvas never changed.
        """
        finished = database.insert("jobs", {
            "project_id": project["id"],
            "type": "generate",
            "status": "completed",
            "payload": {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]},
        })[0]

        response = idle_client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]},
        })

        assert response.status_code == 202, response.text
        assert response.json()["reused"] is False
        assert response.json()["job_id"] != finished["id"]
        assert len(database.select("jobs", [("project_id", f"eq.{project['id']}")])) == 2

    def test_steered_requests_are_never_deduplicated(self, client, project, knowledge_core):
        """Different instructions are different work, even for the same source."""
        base = {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]}
        first = client.post("/api/jobs", json={
            "project_id": project["id"], "type": "generate", "payload": {**base, "instructions": "harder"},
        }).json()
        second = client.post("/api/jobs", json={
            "project_id": project["id"], "type": "generate", "payload": {**base, "instructions": "easier"},
        }).json()

        assert first["job_id"] != second["job_id"]
        assert second["reused"] is False

    def test_a_job_in_another_users_project_is_hidden(self, client, database):
        foreign = database.insert("projects", {"name": "Theirs", "user_id": "someone-else"})[0]
        job = database.insert("jobs", {
            "project_id": foreign["id"], "type": "generate", "status": "pending", "payload": {},
        })[0]
        assert client.get(f"/api/jobs/{job['id']}").status_code == 403

    def test_cancelling_a_finished_job_conflicts(self, client, database, project):
        job = database.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "completed", "payload": {},
        })[0]
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


class TestFlows:
    @staticmethod
    def graph(core_id):
        return {
            "nodes": [
                {"id": "s1", "type": "artifactNode", "data": {"artifact": {"id": core_id}}},
                {"id": "g1", "type": "generator", "data": {"subType": "notes"}},
                {"id": "g2", "type": "generator", "data": {"subType": "quiz"}},
                {"id": "g3", "type": "generator", "data": {"subType": "flashcards"}},
            ],
            "edges": [
                {"id": "e1", "source": "s1", "target": "g1"},
                {"id": "e2", "source": "s1", "target": "g2"},
                {"id": "e3", "source": "g2", "target": "g3"},
            ],
        }

    def test_validate_returns_the_plan_without_running_anything(self, client, project, knowledge_core, database):
        response = client.post(
            f"/api/projects/{project['id']}/flow/validate", json=self.graph(knowledge_core["id"])
        )
        body = response.json()
        assert body["valid"] is True
        assert len(body["steps"]) == 3
        assert body["waves"] == 2
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_validate_explains_why_a_bad_graph_will_not_run(self, client, project, knowledge_core):
        graph = self.graph(knowledge_core["id"])
        graph["edges"].append({"id": "e4", "source": "g3", "target": "g2"})

        body = client.post(f"/api/projects/{project['id']}/flow/validate", json=graph).json()
        assert body["valid"] is False
        assert "cycle" in body["error"]

    def test_run_dispatches_the_first_wave_only(self, client, project, knowledge_core, database):
        response = client.post(
            f"/api/projects/{project['id']}/flow/run", json=self.graph(knowledge_core["id"])
        )
        assert response.status_code == 202, response.text
        states = response.json()["node_states"]

        assert states["g1"]["status"] == "running"
        assert states["g2"]["status"] == "running"
        assert states["g3"]["status"] == "pending", "g3 depends on g2 and must wait"

    def test_run_rejects_an_invalid_graph_with_422(self, client, project):
        response = client.post(f"/api/projects/{project['id']}/flow/run", json={"nodes": [], "edges": []})
        assert response.status_code == 422

    def test_run_falls_back_to_the_saved_canvas(self, client, project, knowledge_core, database):
        """Running with no body uses the persisted canvas_state."""
        database.update("projects", [("id", f"eq.{project['id']}")], {
            "canvas_state": {"viewport": {}, **self.graph(knowledge_core["id"])},
        })
        response = client.post(f"/api/projects/{project['id']}/flow/run", json={})
        assert response.status_code == 202
        assert len(response.json()["node_states"]) == 4


class TestWebSocket:
    def test_snapshot_is_sent_on_connect(self, client, project, database):
        """
        Both halves of the state a canvas joining mid-run has to redraw.

        A client that reconnects gets no replay of the events it missed, so a
        flow left out of the snapshot renders as a canvas with nothing running
        on it while the run is still going.
        """
        job = database.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "running", "payload": {},
        })[0]
        flow_run = database.insert("flow_runs", {
            "project_id": project["id"],
            "status": "running",
            "plan": {"steps": [], "seed_artifacts": {}},
            "node_states": {"g1": {"status": "running"}},
        })[0]

        with client.websocket_connect(f"/ws/projects/{project['id']}?token=mock-token") as socket:
            frame = socket.receive_json()

            assert frame["type"] == "snapshot"
            assert [entry["id"] for entry in frame["data"]["jobs"]] == [job["id"]]
            assert [entry["id"] for entry in frame["data"]["flow_runs"]] == [flow_run["id"]]
            assert frame["data"]["flow_runs"][0]["node_states"] == {"g1": {"status": "running"}}

    def test_events_reach_a_connected_client(self, client, project):
        from backend.services.events import publish

        with client.websocket_connect(f"/ws/projects/{project['id']}?token=mock-token") as socket:
            socket.receive_json()
            publish(project["id"], "job.progress", {"job_id": "j1", "stage": "generating", "percent": 40})

            frame = socket.receive_json()
            assert frame["type"] == "job.progress"
            assert frame["data"]["percent"] == 40

    def test_resync_returns_a_fresh_snapshot(self, client, project):
        with client.websocket_connect(f"/ws/projects/{project['id']}?token=mock-token") as socket:
            socket.receive_json()
            socket.send_json({"type": "resync"})
            assert socket.receive_json()["type"] == "snapshot"

    def test_a_foreign_project_socket_is_refused(self, client, database):
        from starlette.websockets import WebSocketDisconnect

        foreign = database.insert("projects", {"name": "Theirs", "user_id": "someone-else"})[0]
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(f"/ws/projects/{foreign['id']}?token=mock-token") as socket:
                socket.receive_json()
        assert caught.value.code == 4403


class TestSecurity:
    """
    The checks that stop a caller reaching state they do not own.

    Each of these covers a hole that was open once: a job reading someone else's
    artifact, a canvas seeding a flow with one, a project with no owner passing
    every ownership check, an edit repointing an export at another stored file,
    and a YouTube ingest pointed at the local filesystem.
    """

    @staticmethod
    def foreign_artifact(database, artifact_type="knowledge_core"):
        """An artifact sitting in a project owned by somebody else."""
        from backend.tests.conftest import SAMPLE_CORE

        foreign = database.insert("projects", {"name": "Theirs", "user_id": "someone-else"})[0]
        return database.insert("artifacts", {
            "project_id": foreign["id"],
            "type": artifact_type,
            "content": {"kind": "core", "core": SAMPLE_CORE},
        })[0]

    def test_a_generate_source_from_another_users_project_is_refused(self, client, database, project):
        """Owning the destination is not permission to read the source."""
        stolen = self.foreign_artifact(database)

        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "quiz", "source_artifact_ids": [stolen["id"]]},
        })

        assert response.status_code == 403, response.text
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_a_refine_source_from_another_users_project_is_refused(self, client, database, project):
        stolen = self.foreign_artifact(database, artifact_type="notes")

        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "refine",
            "payload": {"source_artifact_id": stolen["id"], "instructions": "rewrite it"},
        })

        assert response.status_code == 403, response.text
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_a_source_in_another_project_of_the_callers_own_is_refused(self, client, database, project):
        """
        Owning both ends is not permission to wire them together.

        Provenance edges are filed under a single project, so a job in one
        project reading a parent that lives in another would commit an edge
        pointing at an artifact this canvas cannot show.
        """
        from backend.api.deps import LOCAL_USER_ID
        from backend.tests.conftest import SAMPLE_CORE

        elsewhere = database.insert("projects", {"name": "Also mine", "user_id": LOCAL_USER_ID})[0]
        core = database.insert("artifacts", {
            "project_id": elsewhere["id"],
            "type": "knowledge_core",
            "content": {"kind": "core", "core": SAMPLE_CORE},
        })[0]

        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "quiz", "source_artifact_ids": [core["id"]]},
        })

        assert response.status_code == 400, response.text
        assert "different project" in response.json()["detail"]
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_a_source_that_does_not_exist_is_refused_before_the_job_is_queued(
        self, client, database, project
    ):
        """An unreadable source is a bad request, not a job that fails later."""
        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {
                "target_type": "quiz",
                "source_artifact_ids": ["00000000-0000-0000-0000-000000000000"],
            },
        })

        assert response.status_code == 404, response.text
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    @staticmethod
    def seeded_graph(artifact_id):
        """A canvas whose one source node names an artifact by id."""
        return {
            "nodes": [
                {"id": "s1", "type": "artifactNode", "data": {"artifact": {"id": artifact_id}}},
                {"id": "g1", "type": "generator", "data": {"subType": "notes"}},
            ],
            "edges": [{"id": "e1", "source": "s1", "target": "g1"}],
        }

    def test_a_flow_seeded_with_another_users_artifact_is_refused(self, client, database, project):
        """
        The canvas is request data, so a seed id is a read the API has to authorise.

        Jobs check their sources, but the flow route reached the same handler by
        another door: nodes came from the body, the compiler lifted their
        artifact ids into the plan, and the engine wrote them straight into a
        generate job's sources.
        """
        stolen = self.foreign_artifact(database)

        response = client.post(
            f"/api/projects/{project['id']}/flow/run", json=self.seeded_graph(stolen["id"])
        )

        assert response.status_code == 403, response.text
        assert "s1" in response.json()["detail"]
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []
        assert database.select("flow_runs", [("project_id", f"eq.{project['id']}")]) == []

    def test_a_saved_canvas_cannot_smuggle_a_foreign_seed_into_a_run(self, client, database, project):
        """Running with no body uses the stored canvas, which is equally caller-written."""
        stolen = self.foreign_artifact(database)
        database.update("projects", [("id", f"eq.{project['id']}")], {
            "canvas_state": {"viewport": {}, **self.seeded_graph(stolen["id"])},
        })

        response = client.post(f"/api/projects/{project['id']}/flow/run", json={})

        assert response.status_code == 403, response.text
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    def test_validating_a_foreign_seed_is_refused_the_same_way(self, client, database, project):
        """Validate compiles the same graph, so it must not report the flow as runnable."""
        stolen = self.foreign_artifact(database)

        response = client.post(
            f"/api/projects/{project['id']}/flow/validate", json=self.seeded_graph(stolen["id"])
        )

        assert response.status_code == 403, response.text

    def test_a_project_with_no_owner_belongs_to_nobody(self, client, database):
        """
        A NULL owner used to satisfy every caller's ownership check.

        Read said yes while list said no, because the listing filters on the
        caller's id and a NULL never matches it.
        """
        orphan = database.insert("projects", {"name": "Unowned", "user_id": None})[0]

        assert client.get(f"/api/projects/{orphan['id']}").status_code == 403
        assert orphan["id"] not in [p["id"] for p in client.get("/api/projects").json()]

    def test_an_unowned_projects_artifacts_are_not_readable(self, client, database):
        orphan = database.insert("projects", {"name": "Unowned", "user_id": None})[0]
        artifact = database.insert("artifacts", {
            "project_id": orphan["id"], "type": "notes", "content": {"data": {"markdown": "secret"}},
        })[0]

        assert client.get(f"/api/artifacts/{artifact['id']}").status_code == 403

    @staticmethod
    def exported_artifact(database, store, project, key, other_key):
        """An artifact with a rendered export, plus a second file to aim at."""
        store.put_bytes(b"the real export", key)
        store.put_bytes(b"somebody elses file", other_key)

        return database.insert("artifacts", {
            "project_id": project["id"],
            "type": "exam",
            "content": {
                "data": {"title": "Midterm"},
                "binary": {"storage_path": key, "format": "pdf", "mime_type": "application/pdf"},
            },
        })[0]

    def test_an_edit_cannot_repoint_an_export_at_another_file(self, client, database, project):
        """
        The export block names a storage key, so writing it is writing a capability.

        It is renderer-owned: an accepted rewrite would have the download
        endpoint sign a link to whatever key the caller named.
        """
        from backend.services.files import get_file_store

        store = get_file_store()
        mine = f"{project['id']}/exports/mine.pdf"
        theirs = f"{project['id']}/exports/theirs.pdf"
        artifact = self.exported_artifact(database, store, project, mine, theirs)

        response = client.patch(f"/api/artifacts/{artifact['id']}", json={
            "content": {
                "data": {"title": "Edited"},
                "binary": {"storage_path": theirs, "format": "pdf", "mime_type": "application/pdf"},
            },
        })

        assert response.status_code == 200, response.text
        assert response.json()["content"]["binary"]["storage_path"] == mine
        assert response.json()["content"]["data"]["title"] == "Edited"

        stored = database.get_artifact(artifact["id"])
        assert stored["content"]["binary"]["storage_path"] == mine

        link = client.get(f"/api/artifacts/{artifact['id']}/download").json()["download_url"]
        assert client.get(link).content == b"the real export"

    def test_an_edit_cannot_attach_an_export_where_there_was_none(self, client, database, project):
        from backend.services.files import get_file_store

        key = f"{project['id']}/exports/private.pdf"
        get_file_store().put_bytes(b"not the callers", key)

        artifact = database.insert("artifacts", {
            "project_id": project["id"], "type": "notes", "content": {"data": {"markdown": "notes"}},
        })[0]

        response = client.patch(f"/api/artifacts/{artifact['id']}", json={
            "content": {"binary": {"storage_path": key, "format": "pdf"}},
        })

        assert response.status_code == 200, response.text
        assert "binary" not in response.json()["content"]
        assert client.get(f"/api/artifacts/{artifact['id']}/download").status_code == 404

    def test_a_youtube_source_pointing_at_the_filesystem_is_refused(self, client, database, project):
        """Given a bare path yt-dlp reads the local file, so the path never reaches it."""
        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "ingest",
            "payload": {
                "source_type": "youtube",
                "source_ref": "/etc/passwd",
                "original_name": "passwd",
            },
        })

        assert response.status_code == 400, response.text
        assert "http(s) URL" in response.json()["detail"]
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []

    @pytest.mark.parametrize("source_ref", [
        "file:///etc/passwd",
        "//evil.com/lecture",
        "ftp://evil.com/lecture.mp4",
        "../../etc/passwd",
    ])
    def test_a_youtube_ref_that_is_not_an_http_url_is_refused(self, source_ref):
        """
        Everything that is not an http(s) URL, not only the absolute path.

        A scheme yt-dlp does not fetch over the network it reads locally, and a
        relative path is a local read with the leading slash filed off.
        """
        from pydantic import ValidationError

        from backend.api.schemas import IngestRequest

        with pytest.raises(ValidationError, match=r"http\(s\) URL"):
            IngestRequest(source_type="youtube", source_ref=source_ref, original_name="lecture")

    def test_a_youtube_url_still_validates(self):
        """The guard rejects those without also rejecting the legitimate case."""
        from backend.api.schemas import IngestRequest

        request = IngestRequest(
            source_type="youtube",
            source_ref="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            original_name="lecture",
        )

        assert request.source_ref == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class TestArtifactEditing:
    def test_an_edit_merges_into_the_stored_content_rather_than_replacing_it(
        self, client, database, project
    ):
        """
        The editor sends the field it changed, not the whole record.

        Everything the pipeline wrote and the editor never shows has to survive
        an edit that names none of it: what kind of content this is, the
        instructions it was steered with, and the revision it was refined from.
        A replacing write loses the lot on the first keystroke saved.
        """
        artifact = database.insert("artifacts", {
            "project_id": project["id"],
            "type": "quiz",
            "content": {
                "kind": "generated",
                "target_type": "quiz",
                "instructions": "focus only on quorums",
                "refined_from": "11111111-1111-1111-1111-111111111111",
                "data": {"title": "Quorums", "questions": []},
            },
        })[0]

        response = client.patch(f"/api/artifacts/{artifact['id']}", json={
            "content": {"data": {"title": "Quorums, revised", "questions": []}},
        })

        assert response.status_code == 200, response.text

        content = response.json()["content"]
        assert content["data"]["title"] == "Quorums, revised"
        assert content["kind"] == "generated"
        assert content["target_type"] == "quiz"
        assert content["instructions"] == "focus only on quorums"
        assert content["refined_from"] == "11111111-1111-1111-1111-111111111111"
        assert content["edited_by_user"] is True
        assert database.get_artifact(artifact["id"])["content"] == content


class StubResolver:
    """Answers with fixed addresses, so a guard test never touches the network."""

    def __init__(self, *answers: str) -> None:
        self._answers = answers

    def addresses(self, host: str) -> list[str]:
        return list(self._answers)


class TestYouTubeIngestGuard:
    """
    The check that stops a `youtube` source fetching something that is not one.

    `source_type: "youtube"` only ever named the field. yt-dlp handed anything
    it did not recognise to its generic extractor, downloaded the response
    whatever it was, and the pipeline stored it, read text out of it and
    committed it as an artifact the caller owns and can read back: a
    full-response SSRF reaching cloud instance metadata, localhost and this
    API's own routes.
    """

    @staticmethod
    def guard(*answers: str):
        from backend.pipeline.ingestion import YouTubeUrlGuard

        return YouTubeUrlGuard(resolver=StubResolver(*answers) if answers else None)

    @pytest.mark.parametrize("url", [
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/admin",
        "http://[fd00::1]/admin",
    ])
    def test_an_internal_address_is_refused(self, url):
        """The proof: the address the exploit reached for is not a YouTube host."""
        from backend.pipeline.ingestion import UnsafeSourceError

        with pytest.raises(UnsafeSourceError):
            self.guard().check(url)

    @pytest.mark.parametrize("url", [
        "http://localhost:8000/api/projects",
        "http://127.0.0.1/latest/meta-data/",
    ])
    def test_a_loopback_url_is_refused(self, url):
        from backend.pipeline.ingestion import UnsafeSourceError

        with pytest.raises(UnsafeSourceError):
            self.guard().check(url)

    @pytest.mark.parametrize("url", [
        "https://youtube.com.evil.tld/watch?v=1",
        "https://notyoutube.com/watch?v=1",
        "https://evil.tld/youtube.com",
        "https://youtu.be.evil.tld/1",
    ])
    def test_a_host_that_only_looks_like_youtube_is_refused(self, url):
        """A suffix match, never a substring one."""
        from backend.pipeline.ingestion import UnsafeSourceError

        with pytest.raises(UnsafeSourceError, match="not a YouTube host"):
            self.guard().check(url)

    def test_a_youtube_host_resolving_inward_is_refused(self):
        """An allowed name is not an allowed destination."""
        from backend.pipeline.ingestion import UnsafeSourceError

        with pytest.raises(UnsafeSourceError, match="not on the public internet"):
            self.guard("10.0.0.5").check("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_one_internal_answer_among_several_is_enough_to_refuse(self):
        from backend.pipeline.ingestion import UnsafeSourceError

        with pytest.raises(UnsafeSourceError, match="not on the public internet"):
            self.guard("142.250.72.14", "127.0.0.1").check("https://youtu.be/dQw4w9WgXcQ")

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
    ])
    def test_a_genuine_youtube_url_passes(self, url):
        """The guard closes the hole without closing the feature."""
        assert self.guard("142.250.72.14").check(url) is None

    def test_the_downloader_never_sees_a_refused_url(self, monkeypatch):
        """The guard runs before yt-dlp is constructed, not after it has fetched."""
        from backend.pipeline import ingestion

        def refuse_to_be_built(*args, **kwargs):
            raise AssertionError("yt-dlp was handed a URL the guard refused")

        monkeypatch.setattr(ingestion.yt_dlp, "YoutubeDL", refuse_to_be_built)

        with pytest.raises(ingestion.UnsafeSourceError):
            ingestion.IngestionService().store_youtube(
                "http://169.254.169.254/latest/meta-data/iam/security-credentials/admin",
                "00000000-0000-0000-0000-000000000000",
            )

    def test_a_refusal_is_a_permanent_failure(self):
        """A refused fetch must not be replayed until the attempt limit."""
        from backend.pipeline.ingestion import UnsafeSourceError
        from backend.services.job_runner import is_transient

        with pytest.raises(UnsafeSourceError) as caught:
            self.guard().check("http://169.254.169.254/latest/meta-data/")

        assert is_transient(caught.value) is False

    def test_a_download_is_capped_at_the_upload_limit(self, monkeypatch):
        """The upload cap covers both ways into the file store, not just one."""
        from backend.core.config import get_settings
        from backend.pipeline import ingestion

        options: dict = {}

        class CapturingDownloader:
            def __init__(self, given):
                options.update(given)

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return False

            def extract_info(self, url, download=True):
                raise RuntimeError("the download stops here")

        monkeypatch.setenv("MAX_FILE_SIZE_MB", "7")
        get_settings.cache_clear()
        monkeypatch.setattr(ingestion.yt_dlp, "YoutubeDL", CapturingDownloader)

        service = ingestion.IngestionService(guard=self.guard("142.250.72.14"))
        with pytest.raises(ingestion.IngestionError):
            service.store_youtube("https://youtu.be/dQw4w9WgXcQ", "a-project")

        assert options["max_filesize"] == 7 * 1024 * 1024

    def test_an_upload_declaring_a_youtube_source_is_refused(self, client, database):
        """
        An upload is a file, so it can never be the source type that is a URL.

        The route checked membership of `SOURCE_TYPES`, which contains
        "youtube", then wrote the payload by hand: the job it queued named a
        path in this server's temp directory as a URL to download.
        """
        project = create_project(client)

        response = client.post(
            f"/api/projects/{project['id']}/upload",
            files={"file": ("lecture.md", io.BytesIO(b"# Lecture" * 20), "text/markdown")},
            data={"source_type": "youtube"},
        )

        assert response.status_code == 400, response.text
        assert "youtube" not in response.json()["detail"]
        assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []


class TestStartupGuard:
    """
    What the API refuses to start with.

    A download link is unforgeable only while its HMAC key is private, and this
    repository publishes two candidate keys: the old default in `config.py` and
    `change-me-in-production` in `.env.example` and `docker-compose.yml`. With
    one of those in place anybody who has read the project can mint a valid link
    for any object in the store with no session at all.
    """

    @staticmethod
    def settings_with(secret: str):
        import dataclasses

        from backend.core.config import get_settings

        return dataclasses.replace(get_settings(), signing_secret=secret)

    @pytest.mark.parametrize("secret", ["", "beeprepared-dev-secret", "change-me-in-production"])
    def test_a_published_signing_secret_refuses_to_boot(self, secret):
        from backend.main import require_unforgeable_links

        with pytest.raises(RuntimeError, match="SIGNING_SECRET"):
            require_unforgeable_links(self.settings_with(secret))

    def test_a_private_signing_secret_boots(self):
        from backend.main import require_unforgeable_links

        assert require_unforgeable_links(self.settings_with("a-private-random-value")) is None

    def test_a_published_default_is_replaced_by_a_minted_one(self, monkeypatch, tmp_path):
        """
        A fresh clone and `docker compose up` both still work.

        `.env.example` and the compose file supply `change-me-in-production`, so
        refusing it outright would break the documented way to start the stack.
        The key is minted instead, and persisted so links survive a restart.
        """
        monkeypatch.setenv("SIGNING_SECRET", "change-me-in-production")
        monkeypatch.setenv("BEE_DATA_DIR", str(tmp_path / "fresh"))

        from backend.core.config import PUBLISHED_SECRETS, get_settings

        get_settings.cache_clear()
        minted = get_settings().signing_secret

        assert minted and minted not in PUBLISHED_SECRETS

        get_settings.cache_clear()
        assert get_settings().signing_secret == minted


class TestFileServing:
    def test_a_signed_link_serves_the_file(self, client, project):
        from backend.services.files import get_file_store

        store = get_file_store()
        store.put_bytes(b"hello world", f"{project['id']}/exports/test.md")
        url = store.signed_url(f"{project['id']}/exports/test.md", filename="test.md")

        response = client.get(url)
        assert response.status_code == 200
        assert response.content == b"hello world"

    def test_a_tampered_signature_is_refused(self, client, project):
        from backend.services.files import get_file_store

        store = get_file_store()
        key = f"{project['id']}/exports/secret.md"
        store.put_bytes(b"secret", key)
        url = store.signed_url(key, filename="secret.md").replace("signature=", "signature=x")

        assert client.get(url).status_code == 403

    def test_path_traversal_is_refused(self, client):
        from backend.services.files import StorageError, get_file_store

        with pytest.raises(StorageError):
            get_file_store().put_bytes(b"pwn", "../../etc/passwd")
