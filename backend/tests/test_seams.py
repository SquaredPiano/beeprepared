"""The abstraction boundaries, exercised through fakes rather than the real thing."""

from __future__ import annotations

import asyncio
import io
import shutil
import tempfile
from contextlib import aclosing
from pathlib import Path
from typing import Any, List, Optional, Tuple, Type

import pytest

from backend.handlers.base import JobHandler
from backend.llm.base import LLMError, LLMProvider, Schema
from backend.models.artifacts import QuizModel
from backend.models.graph import JobBundle
from backend.models.jobs import JobModel
from backend.pipeline.knowledge import KnowledgeCore


class RecordingProvider(LLMProvider):
    """A provider that answers from a script and remembers what it was asked."""

    name = "recording"
    supports_audio = True

    def __init__(self, text: str = "recorded", model: Optional[object] = None) -> None:
        self.text = text
        self.model = model
        self.prompts: List[str] = []
        self.contexts: List[Optional[str]] = []

    async def complete(self, prompt: str, context: Optional[str] = None) -> str:
        self.prompts.append(prompt)
        self.contexts.append(context)
        return self.text

    async def complete_as(
        self,
        prompt: str,
        schema: Type[Schema],
        context: Optional[str] = None,
    ) -> Schema:
        self.prompts.append(prompt)
        self.contexts.append(context)
        if self.model is None:
            raise LLMError("no scripted model")
        return self.model

    async def transcribe(self, audio_path: str) -> str:
        return self.text


@pytest.fixture
def core() -> KnowledgeCore:
    from backend.tests.conftest import SAMPLE_CORE

    return KnowledgeCore(**SAMPLE_CORE)


class TestProviderSubstitution:
    """Any provider can stand in for any other without callers noticing."""

    @pytest.mark.asyncio
    async def test_a_generator_accepts_any_provider(self, core):
        from backend.services.generators import ArtifactGenerator

        quiz = QuizModel(title="Injected", questions=[
            {
                "id": f"Q{index}",
                "text": "?",
                "type": "MCQ",
                "options": ["a", "b", "c", "d"],
                "correct_answer_index": 0,
                "explanation": "because",
                "topic_focus": "consensus",
            }
            for index in range(6)
        ])

        provider = RecordingProvider(model=quiz)
        generated = await ArtifactGenerator(provider).generate("quiz", core)

        assert generated is quiz
        assert core.title in (provider.contexts[0] or "")

    @pytest.mark.asyncio
    async def test_instructions_reach_the_provider(self, core):
        from backend.services.generators import ArtifactGenerator

        provider = RecordingProvider(text="# Notes\n\n" + "content " * 60)
        await ArtifactGenerator(provider).generate("notes", core, "focus on quorums")

        assert "focus on quorums" in provider.prompts[0]
        assert "take precedence" in provider.prompts[0]

    @pytest.mark.asyncio
    async def test_the_offline_provider_satisfies_the_interface(self, core):
        """
        Every type the API advertises, not a sample of them.

        A missing key is meant to degrade the results and nothing else, so a
        type the offline provider has no fixture for is a type that breaks
        outright on a machine with no model configured.
        """
        from backend.llm.offline import OfflineProvider
        from backend.models.artifacts import GENERATED_TYPES
        from backend.services.generators import ArtifactGenerator

        generator = ArtifactGenerator(OfflineProvider())
        for target in sorted(GENERATED_TYPES):
            assert await generator.generate(target, core) is not None, target


class TestGenerationContract:
    """A generator rejects output that parses but would not help anyone."""

    @pytest.mark.asyncio
    async def test_too_few_questions_is_rejected(self, core):
        from backend.services.generators import ArtifactGenerator, GenerationError

        thin = QuizModel(title="Thin", questions=[{
            "id": "Q1",
            "text": "?",
            "type": "MCQ",
            "options": ["a", "b", "c", "d"],
            "correct_answer_index": 0,
            "explanation": "because",
            "topic_focus": "consensus",
        }])

        with pytest.raises(GenerationError, match="at least 5 questions"):
            await ArtifactGenerator(RecordingProvider(model=thin)).generate("quiz", core)

    @pytest.mark.asyncio
    async def test_a_cancelled_exam_batch_is_not_absorbed(self, core):
        """Cancellation is the job being torn down, not one batch coming back empty."""
        import asyncio

        from backend.models.artifacts import ExamSpec
        from backend.services.generators import DEFAULT_EXAM_SPEC, ArtifactGenerator

        class CancellingProvider(RecordingProvider):
            async def complete_as(self, prompt, schema, context=None):
                if schema is ExamSpec:
                    return DEFAULT_EXAM_SPEC
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await ArtifactGenerator(CancellingProvider()).generate("exam", core)

    @pytest.mark.asyncio
    async def test_an_exam_built_from_too_few_questions_is_rejected(self, core):
        """
        A batch that fails is dropped, so a thin exam is the quiet failure mode.

        Nothing raises when two of the three batches go missing: the exam is
        assembled from whatever came back and commits as a finished artifact.
        The floor is what turns three questions into an error instead of a
        final exam somebody sits.
        """
        from backend.models.artifacts import ExamSpec
        from backend.services.generators import (
            DEFAULT_EXAM_SPEC,
            ArtifactGenerator,
            GenerationError,
            QuestionBatch,
        )

        class OneQuestionPerBatch(RecordingProvider):
            async def complete_as(self, prompt, schema, context=None):
                if schema is ExamSpec:
                    return DEFAULT_EXAM_SPEC
                return QuestionBatch(questions=[{
                    "id": "1",
                    "text": "State the intersection property.",
                    "type": "Short Answer",
                    "options": None,
                    "points": 5,
                    "model_answer": "Any two majorities share a node.",
                    "grading_notes": "Full marks for naming the overlap.",
                }])

        with pytest.raises(GenerationError, match="at least 10 exam questions"):
            await ArtifactGenerator(OneQuestionPerBatch()).generate("exam", core)

    @pytest.mark.asyncio
    async def test_notes_below_the_length_floor_are_rejected(self, core):
        from backend.services.generators import ArtifactGenerator, GenerationError

        with pytest.raises(GenerationError, match="at least 200 characters"):
            await ArtifactGenerator(RecordingProvider(text="# Too short")).generate("notes", core)


class TestHandlerInjection:
    """Handlers depend on their collaborators, not on how those are built."""

    @pytest.mark.asyncio
    async def test_a_generate_handler_uses_the_injected_generator(self, database, project, knowledge_core):
        from backend.handlers.generate_handler import GenerateHandler
        from backend.models.jobs import JobModel
        from backend.services.generators import ArtifactGenerator

        quiz = QuizModel(title="From a fake", questions=[
            {
                "id": f"Q{index}",
                "text": "?",
                "type": "MCQ",
                "options": ["a", "b", "c", "d"],
                "correct_answer_index": 0,
                "explanation": "because",
                "topic_focus": "consensus",
            }
            for index in range(6)
        ])

        handler = GenerateHandler(
            database=database,
            generator=ArtifactGenerator(RecordingProvider(model=quiz)),
        )

        row = database.insert("jobs", {
            "project_id": project["id"],
            "type": "generate",
            "status": "pending",
            "payload": {"target_type": "quiz", "source_artifact_ids": [knowledge_core["id"]]},
        })[0]

        bundle = await handler.run(JobModel(**{**row, "status": "running"}))

        assert bundle.artifacts[0].content["data"]["title"] == "From a fake"
        assert len(bundle.edges) == 1


class StubIngestion:
    """Files a source without touching the real store or the network."""

    def store_upload(self, file_path, project_id, original_name, source_type):
        from backend.pipeline.ingestion import StoredSource

        return StoredSource(
            key=f"{project_id}/sources/stub",
            original_name=original_name,
            source_type=source_type,
            size_bytes=Path(file_path).stat().st_size,
        )


class StubExtraction:
    """Returns fixed text, or raises to stand in for an unreadable source."""

    def __init__(self, text: str = "lecture text " * 20, error: Optional[Exception] = None) -> None:
        self.text = text
        self.error = error

    async def extract(self, file_path: str):
        from backend.pipeline.extraction import Extracted

        if self.error:
            raise self.error
        return Extracted(text=self.text)

    async def extract_stored(self, key: str):
        return await self.extract(key)


class StubCleaner:
    """
    Stands in for TextCleaner without touching a provider.

    It mirrors both entry points deliberately. A stub that only implements the
    one method its current callers happen to use will keep passing after the
    real class grows a second, and the drift is invisible until a test that
    needs the other method is written.
    """

    async def clean(self, text: str) -> str:
        return text

    async def clean_transcript(self, text: str, *, use_model: bool = True) -> str:
        return text


class StubKnowledge:
    def __init__(self, core: KnowledgeCore) -> None:
        self.core = core

    async def extract(self, text: str) -> KnowledgeCore:
        return self.core


class TestStagedUploads:
    """
    The upload endpoint stages into the file store and ingest is the last reader.

    The store is on the data volume every process shares, which is what makes
    the job runnable by a worker that did not accept the upload. Releasing the
    slot once the job has succeeded is what keeps every ingested lecture from
    leaving a full-size duplicate behind for as long as the machine stays up.
    """

    @staticmethod
    def stage(project_id: str, tmp_path: Path, suffix: str = ".md") -> str:
        """Stage bytes the way the upload endpoint does and return the key."""
        from backend.services.uploads import UploadStaging

        received = tmp_path / f"received{suffix}"
        received.write_bytes(b"# Lecture\n\nConsensus is hard.")
        return UploadStaging().stage(str(received), project_id, received.name).key

    @staticmethod
    def handler(core: KnowledgeCore, extraction: Optional[StubExtraction] = None):
        from backend.handlers.ingest_handler import IngestHandler

        return IngestHandler(
            ingestion=StubIngestion(),
            extraction=extraction or StubExtraction(),
            cleaner=StubCleaner(),
            knowledge=StubKnowledge(core),
        )

    @staticmethod
    def job(database, project, payload: dict):
        from backend.models.jobs import JobModel

        row = database.insert("jobs", {
            "project_id": project["id"],
            "type": "ingest",
            "status": "pending",
            "payload": {"source_type": "md", "original_name": "lecture.md", **payload},
        })[0]
        return JobModel(**{**row, "status": "running"})

    @staticmethod
    def staged_keys(project) -> List[str]:
        from backend.services.files import get_file_store

        folder = get_file_store().root / project["id"] / "staged"
        return sorted(path.name for path in folder.iterdir()) if folder.exists() else []

    @pytest.mark.asyncio
    async def test_a_successful_ingest_releases_the_staged_upload(
        self, database, project, core, tmp_path
    ):
        key = self.stage(project["id"], tmp_path)

        bundle = await self.handler(core).run(self.job(database, project, {"staged_key": key}))

        assert bundle.result["status"] == "success"
        assert self.staged_keys(project) == []

    @pytest.mark.asyncio
    async def test_a_failed_ingest_keeps_the_staged_upload_for_the_retry(
        self, database, project, core, tmp_path
    ):
        """
        A retryable failure must not cost the caller their file.

        Releasing the slot in a `finally` made every retry fail for a second,
        unrelated reason: the attempt the runner requeued found nothing left to
        read. The staged copy is the only copy of what was uploaded until the
        source is stored, and the run that eventually succeeds is the one that
        releases it.
        """
        key = self.stage(project["id"], tmp_path)
        handler = self.handler(core, StubExtraction(error=RuntimeError("unreadable")))

        with pytest.raises(RuntimeError, match="unreadable"):
            await handler.run(self.job(database, project, {"staged_key": key}))

        assert self.staged_keys(project) == [Path(key).name]

    @pytest.mark.asyncio
    async def test_another_projects_staged_upload_is_not_readable(
        self, database, project, core, tmp_path
    ):
        """A key is quoted back by the payload, so it is a caller's string to choose."""
        from backend.api.deps import LOCAL_USER_ID
        from backend.services.uploads import StagingError

        elsewhere = database.insert("projects", {
            "name": "Another Project", "description": "fixture", "user_id": LOCAL_USER_ID,
        })[0]
        theirs = self.stage(elsewhere["id"], tmp_path)

        with pytest.raises(StagingError, match="not an upload staged by"):
            await self.handler(core).run(self.job(database, project, {"staged_key": theirs}))

        assert self.staged_keys(elsewhere) == [Path(theirs).name]

    @pytest.mark.asyncio
    async def test_a_filesystem_path_is_not_a_source(self, database, project, core, tmp_path):
        """
        An uploaded source is named by a key, and nothing else names a file.

        A payload naming a path used to be read, extracted and committed as an
        artifact the caller could download, which made any ingest job an
        arbitrary read of the server's disk.
        """
        theirs = tmp_path / "my-lecture.md"
        theirs.write_text("# Lecture\n\nConsensus is hard.")

        with pytest.raises(ValueError, match="must carry the staged_key"):
            await self.handler(core).run(self.job(database, project, {"source_ref": str(theirs)}))

        assert theirs.exists()

    def test_only_a_staged_upload_can_be_released(self, project, tmp_path):
        """
        The one delete in the ingest path refuses everything but a staging slot.

        Leaking a staged file costs disk; deleting a stored source costs the
        project its artifact, so the shape of the key is checked before the
        store is touched at all.
        """
        from backend.services.files import get_file_store
        from backend.services.uploads import StagingError, UploadStaging

        store = get_file_store()
        source_key = f"{project['id']}/sources/lecture.md"
        store.put_bytes(b"# Lecture", source_key)

        for key in (source_key, f"{project['id']}/staged/../sources/lecture.md"):
            with pytest.raises(StagingError, match="not an upload staged by"):
                UploadStaging().discard(key, project["id"])

        assert store.exists(source_key)


class TestCrossProcessIngest:
    """
    The process that accepts an upload is not the process that ingests it.

    Dispatch to Celery and the API and the workers are separate containers that
    share one thing: the data volume. A job whose payload named a path in the
    API's temp directory could not be run there at all, and every upload failed
    with `No readable file at /tmp/...` from a worker looking in its own empty
    one. These tests refuse to let that come back by never letting the executing
    side inherit anything: the accepting side's temp directory is destroyed and
    replaced before the job runs, and the singletons are dropped so the store,
    the database and the settings are resolved again from configuration, with
    the handler built only afterwards. What survives the split is the data
    volume, because in the deployment that is what is mounted into both.
    """

    @staticmethod
    def upload(client, project_id: str, body: bytes) -> str:
        response = client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("lecture.md", io.BytesIO(body), "text/markdown")},
            data={"source_type": "md"},
        )
        assert response.status_code == 202, response.text
        return response.json()["job_id"]

    @pytest.mark.asyncio
    async def test_a_worker_sharing_only_the_data_volume_can_run_an_upload(
        self, idle_client, core, monkeypatch, tmp_path
    ):
        from backend.core.config import get_settings
        from backend.handlers.ingest_handler import IngestHandler
        from backend.models.jobs import JobType
        from backend.services import database as database_module
        from backend.services import files
        from backend.services.database import get_database
        from backend.services.job_runner import JobExecutor

        accepting_tmp = tmp_path / "api-tmp"
        accepting_tmp.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(accepting_tmp))

        project = idle_client.post("/api/projects", json={"name": "Split"}).json()
        job_id = self.upload(idle_client, project["id"], b"# Lecture\n\n" + b"consensus " * 40)

        executing_tmp = tmp_path / "worker-tmp"
        executing_tmp.mkdir()
        shutil.rmtree(accepting_tmp)
        monkeypatch.setattr(tempfile, "tempdir", str(executing_tmp))
        get_settings.cache_clear()
        files.reset_file_store()
        database_module.reset_database()

        worker_handler = IngestHandler(cleaner=StubCleaner(), knowledge=StubKnowledge(core))
        monkeypatch.setitem(JobExecutor.HANDLERS, JobType.INGEST.value, lambda: worker_handler)

        assert await JobExecutor().run_job(job_id) is True

        worker_database = get_database()
        assert worker_database.get_job(job_id)["status"] == "completed"

        stored = worker_database.select("artifacts", [("project_id", f"eq.{project['id']}")])
        assert {artifact["type"] for artifact in stored} == {"md", "knowledge_core"}

        source = next(artifact for artifact in stored if artifact["type"] == "md")
        assert files.get_file_store().exists(source["content"]["storage_key"])

    @pytest.mark.asyncio
    async def test_the_worker_never_reads_the_accepting_process_temp_directory(
        self, idle_client, monkeypatch, tmp_path
    ):
        """
        Whatever the API buffered through is gone by the time the job is queued.

        The staged copy the worker reads has to be the one in the store, so the
        temp file the request streamed through must not outlive the request: a
        second reader of it is a second thing to clean up and a path that would
        work in tests and fail in a container.
        """
        buffering = tmp_path / "api-tmp"
        buffering.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(buffering))

        project = idle_client.post("/api/projects", json={"name": "No leftovers"}).json()
        self.upload(idle_client, project["id"], b"# Lecture\n\n" + b"consensus " * 40)

        assert list(buffering.iterdir()) == []


class TestEventBusIsolation:
    """
    A subscriber is subscribed to one project, not to the bus.

    Every open canvas holds a socket, and the bus is the only thing keeping one
    workspace's job progress, artifact names and chat replies out of another's.
    Delivery is by project id, so widening the lookup leaks everything at once
    and looks like nothing at all in a single-project test.
    """

    @staticmethod
    async def first_event(bus, project_id: str):
        """Subscribe, hand back the first event delivered, and unsubscribe."""
        async with aclosing(bus.subscribe(project_id)) as stream:
            async for event in stream:
                return event
        return None

    @pytest.mark.asyncio
    async def test_a_subscriber_never_sees_another_projects_events(self):
        from backend.services.events import InProcessEventBus, make_event

        bus = InProcessEventBus()
        bus.bind_loop(asyncio.get_running_loop())

        watcher = asyncio.create_task(self.first_event(bus, "project-a"))
        await asyncio.sleep(0.05)

        bus.publish("project-b", make_event("job.completed", "project-b", {"job_id": "theirs"}))
        await asyncio.sleep(0.05)
        assert not watcher.done(), "a subscriber to project-a was handed project-b's event"

        bus.publish("project-a", make_event("job.completed", "project-a", {"job_id": "mine"}))
        delivered = await asyncio.wait_for(watcher, timeout=5)

        assert delivered["project_id"] == "project-a"
        assert delivered["data"]["job_id"] == "mine"


class TestFileStoreContract:
    """Signed links are the credential, so the signature has to be load-bearing."""

    def test_a_link_survives_a_round_trip(self, tmp_path):
        from backend.services.files import FileStore

        store = FileStore(tmp_path / "files", "secret")
        store.put_bytes(b"payload", "project/exports/file.md")

        url = store.signed_url("project/exports/file.md", filename="file.md")
        expires = int(url.split("expires=")[1].split("&")[0])
        signature = url.split("signature=")[1].split("&")[0]

        assert store.verify("project/exports/file.md", expires, signature)

    def test_an_expired_link_is_refused(self, tmp_path):
        from backend.services.files import FileStore

        store = FileStore(tmp_path / "files", "secret")
        assert not store.verify("k", 0, store.sign("k", 0))

    def test_a_key_signed_elsewhere_is_refused(self, tmp_path):
        from backend.services.files import FileStore

        mine = FileStore(tmp_path / "mine", "secret")
        theirs = FileStore(tmp_path / "theirs", "different-secret")

        assert not mine.verify("k", 9_999_999_999, theirs.sign("k", 9_999_999_999))

    def test_keys_cannot_escape_the_store_root(self, tmp_path):
        from backend.services.files import FileStore, StorageError

        store = FileStore(tmp_path / "files", "secret")
        with pytest.raises(StorageError):
            store.resolve("../../etc/passwd")


def claimed_job(database, project_id: str, job_type: str = "generate") -> JobModel:
    """Queue a job and claim it, the way a worker would."""
    row = database.insert("jobs", {
        "project_id": project_id, "type": job_type, "status": "pending", "payload": {},
    })[0]
    return database.claim_job(row["id"])


class Rendezvous:
    """
    Holds every arrival until all of them are in.

    Lives in its own object because a handler is copied per job: a counter kept
    on the handler would be copied too, and the runs would never meet.
    """

    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.arrived = 0
        self.everyone_here = asyncio.Event()

    async def wait(self) -> None:
        self.arrived += 1
        if self.arrived >= self.expected:
            self.everyone_here.set()
        await self.everyone_here.wait()


class PausingHandler(JobHandler):
    """
    Reports one stage, waits for every concurrent run, then reports another.

    The wait builds the interleaving rather than hoping for it: both jobs are
    inside `run` with their reporters attached before either publishes its
    second stage.
    """

    def __init__(self, rendezvous: Rendezvous) -> None:
        self._rendezvous = rendezvous

    async def run(self, job: JobModel) -> JobBundle:
        self.report("before the pause", 10)
        await self._rendezvous.wait()
        self.report("after the pause", 55)
        return JobBundle(job_id=job.id, project_id=job.project_id, result={"status": "success"})


class FailingHandler(JobHandler):
    """Raises whatever the test wants the runner to classify."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def run(self, job: JobModel) -> JobBundle:
        raise self._error


class RecordingDispatcher:
    """
    Stands in for the real dispatcher and remembers the row's status at hand-off.

    The status is what proves the ordering rule: a job dispatched before its
    requeue is committed would be claimed by a worker that still sees `running`.
    """

    def __init__(self, database) -> None:
        self._database = database
        self.job_ids: List[str] = []
        self.statuses: List[str] = []

    def __call__(self, job_id: str) -> str:
        self.job_ids.append(str(job_id))
        self.statuses.append(self._database.get_job(job_id)["status"])
        return "recorded"


class TestProgressAttribution:
    """
    One handler serves every worker, so a reporter must not be attached by mutation.

    A mutated reporter is not a lost event: the job that attached last owns the
    callback, so a job still in flight publishes its progress into somebody
    else's project under somebody else's job id.
    """

    @staticmethod
    def record_events(monkeypatch) -> List[Tuple[str, str, Any]]:
        published: List[Tuple[str, str, Any]] = []
        monkeypatch.setattr(
            "backend.services.job_runner.publish",
            lambda project_id, event_type, data=None: published.append(
                (str(project_id), event_type, data)
            ),
        )
        return published

    @staticmethod
    def progress_events(published) -> List[Tuple[str, str, str]]:
        from backend.services.events import JOB_PROGRESS

        return sorted(
            (project_id, data["job_id"], data["stage"])
            for project_id, event_type, data in published
            if event_type == JOB_PROGRESS
        )

    @pytest.mark.asyncio
    async def test_concurrent_jobs_report_under_their_own_identity(
        self, database, project, monkeypatch
    ):
        from backend.api.deps import LOCAL_USER_ID
        from backend.models.jobs import JobType
        from backend.services.job_runner import JobExecutor

        elsewhere = database.insert("projects", {
            "name": "Another Project", "description": "fixture", "user_id": LOCAL_USER_ID,
        })[0]

        published = self.record_events(monkeypatch)
        shared = PausingHandler(Rendezvous(2))
        monkeypatch.setitem(JobExecutor.HANDLERS, JobType.GENERATE.value, lambda: shared)

        executor = JobExecutor(database)
        here, there = claimed_job(database, project["id"]), claimed_job(database, elsewhere["id"])

        assert await asyncio.gather(executor.execute(here), executor.execute(there)) == [True, True]

        assert self.progress_events(published) == sorted([
            (project["id"], str(here.id), "before the pause"),
            (project["id"], str(here.id), "after the pause"),
            (elsewhere["id"], str(there.id), "before the pause"),
            (elsewhere["id"], str(there.id), "after the pause"),
        ])

    @pytest.mark.asyncio
    async def test_attaching_a_reporter_leaves_the_shared_handler_alone(self, database):
        from backend.models.jobs import JobType
        from backend.services.job_runner import JobExecutor

        executor = JobExecutor(database)
        shared = executor.handler_for(JobType.GENERATE.value)

        attached = shared.with_progress(lambda stage, percent: None)

        assert attached is not shared
        assert "progress" not in vars(shared)
        assert executor.handler_for(JobType.GENERATE.value) is shared


class TestRetryDispatch:
    """
    A requeued job only runs again if somebody is told it is queued.

    The local pool polls and would find it eventually; Celery workers only ever
    run what they are sent, so without this the retry waits on the periodic
    drain and, without that, forever.
    """

    @pytest.mark.asyncio
    async def test_a_retryable_failure_is_dispatched_again(self, database, project, monkeypatch):
        from backend.models.jobs import JobType
        from backend.services.job_runner import JobExecutor

        monkeypatch.setitem(
            JobExecutor.HANDLERS,
            JobType.GENERATE.value,
            lambda: FailingHandler(TimeoutError("upstream timed out")),
        )

        dispatcher = RecordingDispatcher(database)
        job = claimed_job(database, project["id"])

        assert await JobExecutor(database, dispatch=dispatcher).execute(job) is False

        assert database.get_job(job.id)["status"] == "pending"
        assert dispatcher.job_ids == [str(job.id)]
        assert dispatcher.statuses == ["pending"]

    @pytest.mark.asyncio
    async def test_a_permanent_failure_is_not_dispatched_again(self, database, project, monkeypatch):
        from backend.models.jobs import JobType
        from backend.services.job_runner import JobExecutor

        monkeypatch.setitem(
            JobExecutor.HANDLERS,
            JobType.GENERATE.value,
            lambda: FailingHandler(ValueError("target_type is required")),
        )

        dispatcher = RecordingDispatcher(database)
        job = claimed_job(database, project["id"])

        assert await JobExecutor(database, dispatch=dispatcher).execute(job) is False

        assert database.get_job(job.id)["status"] == "failed"
        assert dispatcher.job_ids == []
