"""HTTP and WebSocket surface: the contract, ownership rules and the event stream."""

from __future__ import annotations

import io

import pytest


def create_project(client, name="API Project") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


class TestMeta:
    def test_health_reports_what_it_is_wired_to(self, client):
        body = client.get("/health").json()
        assert body["status"] == "healthy"
        assert body["model"] == "offline"
        assert body["jobs"] in {"local", "celery"}

    def test_capabilities_lists_every_artifact_type(self, client):
        body = client.get("/api/capabilities").json()
        assert "mindmap" in body["artifact_types"]
        assert "cheatsheet" in body["artifact_types"]
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
    def test_upload_queues_an_ingest_job(self, client):
        project = create_project(client)
        response = client.post(
            f"/api/projects/{project['id']}/upload",
            files={"file": ("lecture.md", io.BytesIO(b"# Lecture\n\nConsensus is hard." * 20), "text/markdown")},
            data={"source_type": "md"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["job_id"]

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
    def test_create_and_read_a_generate_job(self, client, database, knowledge_core, project):
        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]},
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["job_id"]

        status = client.get(f"/api/jobs/{job_id}")
        assert status.status_code == 200
        assert status.json()["type"] == "generate"

    def test_invalid_target_type_is_a_400_with_a_useful_message(self, client, project, knowledge_core):
        response = client.post("/api/jobs", json={
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "horoscope", "source_artifact_ids": [knowledge_core["id"]]},
        })
        assert response.status_code == 400
        assert "target_type must be one of" in response.json()["detail"]

    def test_identical_in_flight_requests_are_deduplicated(self, client, project, knowledge_core):
        payload = {
            "project_id": project["id"],
            "type": "generate",
            "payload": {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]},
        }
        first = client.post("/api/jobs", json=payload).json()
        second = client.post("/api/jobs", json=payload).json()

        assert second["reused"] is True
        assert second["job_id"] == first["job_id"]

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
        database.insert("jobs", {
            "project_id": project["id"], "type": "generate", "status": "running", "payload": {},
        })
        with client.websocket_connect(f"/ws/projects/{project['id']}?token=mock-token") as socket:
            frame = socket.receive_json()
            assert frame["type"] == "snapshot"
            assert len(frame["data"]["jobs"]) == 1

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

        assert orphan["user_id"] is None
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

    def test_a_youtube_url_still_validates(self):
        """The guard rejects paths without also rejecting the legitimate case."""
        from backend.api.schemas import IngestRequest

        request = IngestRequest(
            source_type="youtube",
            source_ref="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            original_name="lecture",
        )

        assert request.source_ref.startswith("https://")


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
