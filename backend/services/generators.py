"""Turns a knowledge core into one typed study artifact."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Type

from pydantic import BaseModel

from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider
from backend.models.artifacts import (
    CheatSheetModel,
    ExamQuestion,
    ExamSpec,
    FinalExamModel,
    FlashcardModel,
    MindMapModel,
    NotesModel,
    QuizModel,
    SlidesModel,
    StudyGuideModel,
)
from backend.pipeline.knowledge import KnowledgeCore

logger = logging.getLogger(__name__)

MIN_EXAM_QUESTIONS = 10


class GenerationError(RuntimeError):
    """Raised when a generator couldn't come back with anything usable."""


class QuestionBatch(BaseModel):
    """One batch of exam questions, all of the same type."""

    questions: List[ExamQuestion]


@dataclass(frozen=True)
class GeneratorSpec:
    """
    Everything that makes one artifact type different from another.

    That's the whole point of the table below. A new kind of artifact is one more
    entry in `SPECS`: there's no new method to write, no new branch to add to the
    handler, and no validation rule living somewhere else that you have to
    remember to update.
    """

    prompt: str
    schema: Optional[Type[BaseModel]] = None
    required_field: Optional[str] = None
    minimum_items: int = 0
    minimum_characters: int = 0

    def validate(self, model: BaseModel) -> None:
        """
        Throw out an artifact that parsed cleanly but is too thin to use.

        A quiz with two questions is perfectly good JSON. It still isn't a quiz,
        and the user would rather see an error than open that and find out.
        """
        data = model.model_dump()

        if self.minimum_characters:
            body = data.get("body") or ""
            if len(body) < self.minimum_characters:
                raise GenerationError(
                    f"Expected at least {self.minimum_characters} characters, got {len(body)}"
                )

        if self.required_field:
            items = data.get(self.required_field) or []
            if len(items) < self.minimum_items:
                raise GenerationError(
                    f"Expected at least {self.minimum_items} {self.required_field}, got {len(items)}"
                )


SPECS: Dict[str, GeneratorSpec] = {
    "quiz": GeneratorSpec(
        schema=QuizModel,
        required_field="questions",
        minimum_items=5,
        prompt="""
You are an expert examiner writing a practice quiz.

Write 10-15 questions covering the source material.

Rules:
1. Mix True/False and MCQ.
2. Cover the most important concepts, not the most obscure ones.
3. Distractors must be plausible. Never use "all of the above".
4. Every question must be answerable from the source material alone.
5. The explanation is what the learner reads to understand the answer.
6. Use LaTeX for all mathematics.
""",
    ),
    "flashcards": GeneratorSpec(
        schema=FlashcardModel,
        required_field="cards",
        minimum_items=5,
        prompt="""
You are an expert tutor building a spaced-repetition deck.

Write 15-20 flashcards from the source material.

Rules:
1. One idea per card. Split compound facts into separate cards.
2. Fronts must be answerable without seeing the back.
3. Keep backs short enough to recall in one go.
4. Use LaTeX for all mathematics.
""",
    ),
    "slides": GeneratorSpec(
        schema=SlidesModel,
        required_field="slides",
        minimum_items=3,
        prompt="""
You are a content designer building a teaching deck.

Produce 10-12 slides covering the source material.

Rules:
1. Open with a title slide and close with a summary slide.
2. Bullets are prompts for the speaker, not paragraphs.
3. Every slide needs speaker notes that say what to explain.
4. Use LaTeX for all mathematics.
""",
    ),
    "notes": GeneratorSpec(
        minimum_characters=200,
        prompt="""
You are an expert academic note-taker.

Write detailed study notes in Markdown from the source material.

Rules:
1. Open with a single `#` title.
2. Organise into `##` sections and `###` subsections.
3. Use bullets for key concepts and bold for terms being defined.
4. Use LaTeX for all mathematics: $...$ inline, $$...$$ for display.
5. Include definitions, worked examples and a "Key takeaways" section.

Output pure Markdown. No JSON, no surrounding code fence.
""",
    ),
    "study_guide": GeneratorSpec(
        schema=StudyGuideModel,
        required_field="objectives",
        minimum_items=3,
        prompt="""
You are a learning designer building a revision plan for one study session.

Rules:
1. Order by dependency: prerequisites before the ideas that need them.
2. Give a time estimate per section and say what to skip if short on time.
3. The checklist must cover every objective.
4. Use LaTeX for all mathematics.
""",
    ),
    "cheatsheet": GeneratorSpec(
        schema=CheatSheetModel,
        required_field="sections",
        minimum_items=2,
        prompt="""
You are producing a dense one-page reference sheet.

Condense the source material into scannable sections.

Rules:
1. Entries are single lines, never paragraphs, and stay under 120 characters.
2. Prefer formulas, thresholds, definitions and edge cases over prose.
3. Group by topic so it can be scanned under exam pressure.
4. Use LaTeX for every formula.
""",
    ),
    "mindmap": GeneratorSpec(
        schema=MindMapModel,
        prompt="""
You are mapping the conceptual structure of the source material.

Rules:
1. The root is the subject of the material.
2. Produce 4-7 branches, each with 2-4 leaves. The tree is exactly three levels
   deep: root, branch, leaf. Do not nest further.
3. Branches are concepts, not section titles. Show how the ideas relate.
4. Leaves are concrete: a definition, a formula, an example.
5. Labels are at most six words. Details are one sentence under 140 characters.
""",
    ),
}

EXAM_SPEC_PROMPT = """
You are an academic assessment designer.

Define the assessment contract for the provided material: the discipline, the
style of exam that suits it, the cognitive targets worth testing, and how
partial credit should be awarded.
"""

DEFAULT_EXAM_SPEC = ExamSpec(
    discipline="General",
    exam_style="Standard academic",
    cognitive_targets=["Recall", "Understanding", "Application"],
    grading_philosophy="Award partial credit for correct reasoning.",
    instructions_tone="Formal",
)

EXAM_BATCHES = (("MCQ", 15, 3), ("Short Answer", 5, 5), ("Problem Set", 3, 10))


class ArtifactGenerator:
    """
    Builds each artifact type from its spec.

    The exam is the honest exception and gets a method of its own. It needs two
    model calls, one to settle the assessment contract and then one per batch of
    questions, and that doesn't fit in a table row.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    async def generate(
        self,
        target_type: str,
        core: KnowledgeCore,
        instructions: Optional[str] = None,
    ) -> BaseModel:
        """Produce an artifact of `target_type`, and check it's worth keeping."""
        if target_type == "exam":
            return await self._exam(core, instructions)

        spec = SPECS.get(target_type)
        if spec is None:
            raise GenerationError(f"Unknown artifact type: {target_type}")

        logger.info("Generating %s", target_type)
        prompt = self._steer(spec.prompt, instructions)
        context = core.model_dump_json()

        model = (
            await self._provider.complete_as(prompt, spec.schema, context=context)
            if spec.schema
            else self._as_notes(await self._provider.complete(prompt, context=context), core)
        )
        spec.validate(model)
        return model

    async def _exam(self, core: KnowledgeCore, instructions: Optional[str]) -> FinalExamModel:
        """
        Build an exam in two passes.

        First we ask the model for an assessment contract: the discipline, the
        style of exam, what's worth testing, how to award partial credit. Then
        every question batch is written against that contract. The three batches
        don't depend on each other, so `asyncio.gather` runs them all at once.

        A batch that fails gets dropped and we build the exam from the rest. A
        batch that was cancelled is a different matter. Cancellation means
        something is tearing us down, and quietly turning that into a shorter
        exam would hide it, so we re-raise.

        We sort the results on `BaseException`, not `Exception`, because `gather`
        can hand back things that aren't `Exception` subclasses, `CancelledError`
        among them. Anything narrower and one of those slips through to `extend`,
        which treats it as a list of questions.
        """
        context = core.model_dump_json(indent=2)
        spec = await self._exam_spec(context, instructions)

        results = await asyncio.gather(
            *(self._exam_batch(context, spec, kind, count, points, instructions)
              for kind, count, points in EXAM_BATCHES),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result

        questions: List[ExamQuestion] = []
        for (kind, _, _), result in zip(EXAM_BATCHES, results):
            if isinstance(result, BaseException):
                logger.warning("Exam batch '%s' failed: %s", kind, result)
                continue
            questions.extend(result)

        if len(questions) < MIN_EXAM_QUESTIONS:
            raise GenerationError(
                f"Expected at least {MIN_EXAM_QUESTIONS} exam questions, got {len(questions)}"
            )

        for number, question in enumerate(questions, start=1):
            question.id = f"Q-{number}"

        return FinalExamModel(
            title=f"Final exam: {core.title}",
            exam_spec=spec,
            instructions=f"({spec.instructions_tone}) {spec.exam_style}. Answer all questions.",
            rubric=spec.grading_philosophy,
            questions=questions,
        )

    async def _exam_spec(self, context: str, instructions: Optional[str]) -> ExamSpec:
        try:
            return await self._provider.complete_as(
                self._steer(EXAM_SPEC_PROMPT, instructions), ExamSpec, context=context
            )
        except Exception as error:
            logger.warning("Exam spec generation failed (%s); using the default contract", error)
            return DEFAULT_EXAM_SPEC

    async def _exam_batch(
        self,
        context: str,
        spec: ExamSpec,
        kind: str,
        count: int,
        points: int,
        instructions: Optional[str],
    ) -> List[ExamQuestion]:
        prompt = self._steer(f"""
You are an examiner working to a fixed assessment contract.

Discipline: {spec.discipline}
Style: {spec.exam_style}
Grading philosophy: {spec.grading_philosophy}
Cognitive targets: {", ".join(spec.cognitive_targets)}

Write EXACTLY {count} questions of type "{kind}", worth {points} points each.

Rules:
1. Exactly {count} questions, no more and no fewer.
2. Every question needs a model answer and grading notes that say where the
   marks are.
3. MCQ questions need four plausible options. Other types have none.
4. Use LaTeX for all mathematics.
""", instructions)

        batch = await self._provider.complete_as(prompt, QuestionBatch, context=context)
        return batch.questions

    @staticmethod
    def _steer(prompt: str, instructions: Optional[str]) -> str:
        """
        Bolt the user's own instructions onto the end of a prompt.

        They go last, and they're labelled as outranking what came before, so
        where the user contradicts one of our rules the user wins.
        """
        if not instructions or not instructions.strip():
            return prompt
        return (
            f"{prompt}\n"
            "--- USER INSTRUCTIONS (these take precedence over the rules above) ---\n"
            f"{instructions.strip()}\n"
        )

    @staticmethod
    def _as_notes(body: str, core: KnowledgeCore) -> NotesModel:
        if not body or not body.strip():
            raise GenerationError("The model returned no note text")

        body = body.strip()
        first_line = body.splitlines()[0] if body.splitlines() else ""
        title = first_line[2:].strip() if first_line.startswith("# ") else f"Notes: {core.title}"
        return NotesModel(title=title, body=body)
