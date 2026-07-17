"""The abstraction boundaries, exercised through fakes rather than the real thing."""

from __future__ import annotations

from typing import List, Optional, Type

import pytest

from backend.llm.base import LLMError, LLMProvider, Schema
from backend.models.artifacts import QuizModel
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
        from backend.llm.offline import OfflineProvider
        from backend.services.generators import ArtifactGenerator

        generator = ArtifactGenerator(OfflineProvider())
        for target in ("quiz", "flashcards", "notes", "mindmap"):
            assert await generator.generate(target, core) is not None


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
