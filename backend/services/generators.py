"""
Artifact generation.

Every generated artifact type is described by a single ``GeneratorSpec`` entry:
its prompt, its output schema, and how many items a usable result must contain.
Adding a type is one table entry, not a new method plus a new branch in the
handler plus a new validation rule.

Two properties this module is responsible for:

**Concurrency.** Generation is async all the way down and calls
``generate_content_async``. The exam builder issues its three question batches
with ``asyncio.gather`` instead of one after another, so a fan-out of generator
nodes overlaps instead of serialising behind a single blocking call.

**Steerability.** Every generator accepts free-text ``instructions``. That is
what powers the assistant panel: "make the quiz harder", "focus on chapter 3"
is appended to the prompt and the artifact is regenerated.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from backend.core.knowledge_core import KnowledgeCore
from backend.core.llm_interface import LLMProvider
from backend.core.services.llm_factory import LLMFactory
from backend.models.artifacts import (
    CheatSheetModel,
    ExamQuestion,
    ExamSpec,
    FinalExamModel,
    FlashcardModel,
    MarkdownNotesModel,
    MindMapModel,
    QuizModel,
    SlidesModel,
    StudyGuideModel,
)

logger = logging.getLogger(__name__)


class QuestionBatch(BaseModel):
    """Structured-output wrapper for one batch of exam questions."""
    questions: List[ExamQuestion]


class GenerationError(RuntimeError):
    """Raised when a generator could not produce a usable artifact."""


@dataclass(frozen=True)
class GeneratorSpec:
    """Everything that distinguishes one artifact type from another."""

    target_type: str
    prompt: str
    schema: Optional[Type[BaseModel]] = None   # None => free-form markdown
    min_field: Optional[str] = None            # collection that must be populated
    min_count: int = 0
    min_chars: int = 0                         # for markdown-shaped artifacts


SPECS: Dict[str, GeneratorSpec] = {
    "quiz": GeneratorSpec(
        target_type="quiz",
        schema=QuizModel,
        min_field="questions",
        min_count=5,
        prompt="""
You are an expert examiner writing a practice quiz.

**Task**: Write 10-15 quiz questions covering the source material.

**Each question needs**:
- "id": unique identifier ("Q1", "Q2", ...)
- "text": the question. Use LaTeX for maths ($x^2$)
- "type": "True/False" or "MCQ"
- "options": ["True", "False"] for T/F, four plausible options for MCQ
- "correct_answer_index": 0-based index into options
- "explanation": why that answer is right - this is what the learner reads
- "topic_focus": the specific concept under test

**Rules**:
1. Mix True/False and MCQ.
2. Cover the most important concepts, not the most obscure ones.
3. Distractors must be plausible; never use "all of the above".
4. Every question must be answerable from the source material alone.
""",
    ),
    "flashcards": GeneratorSpec(
        target_type="flashcards",
        schema=FlashcardModel,
        min_field="cards",
        min_count=5,
        prompt="""
You are an expert tutor building a spaced-repetition deck.

**Task**: Write 15-20 flashcards from the source material.

**Each card needs**: "front" (question/prompt), "back" (answer), optional "hint".

**Rules**:
1. One idea per card. Split compound facts into separate cards.
2. Fronts must be answerable without seeing the back.
3. Keep backs short enough to recall in one go.
4. Use LaTeX for all mathematical notation.
""",
    ),
    "slides": GeneratorSpec(
        target_type="slides",
        schema=SlidesModel,
        min_field="slides",
        min_count=3,
        prompt="""
You are a content designer building a teaching deck.

**Task**: Produce 10-12 slides covering the source material.

**Each slide needs**: "heading", "main_idea" (one sentence), "bullet_points"
(3-5, brief), "visual_cue" (what to draw), "speaker_notes" (what to say).

**Rules**:
1. Open with a title slide and close with a summary slide.
2. Bullets are prompts for the speaker, not paragraphs.
3. Use LaTeX for mathematical expressions.
""",
    ),
    "notes": GeneratorSpec(
        target_type="notes",
        schema=None,
        min_chars=200,
        prompt="""
You are an expert academic note-taker.

**Task**: Write detailed study notes in Markdown from the source material.

**Requirements**:
1. Open with a single `#` title.
2. Organise into `##` sections and `###` subsections.
3. Use bullets for key concepts and bold for terms being defined.
4. Use LaTeX for all mathematics ($...$ inline, $$...$$ block).
5. Include definitions, worked examples and a "Key Takeaways" section.

**Output**: pure Markdown. No JSON, no code fences around the whole document.
""",
    ),
    "study_guide": GeneratorSpec(
        target_type="study_guide",
        schema=StudyGuideModel,
        min_field="objectives",
        min_count=3,
        prompt="""
You are a learning designer building a revision plan for one study session.

**Task**: Produce a study guide for the source material.

**Fields**:
- "estimated_minutes": realistic time to work through the whole guide
- "objectives": learning objectives, most important first
- "body": Markdown, ordered the way a learner should actually work through it,
  with time estimates per section
- "checklist": self-check questions covering every objective

**Rules**:
1. Order by dependency: prerequisites before the ideas that need them.
2. Say what to skip if short on time.
3. Use LaTeX for mathematics.
""",
    ),
    "cheatsheet": GeneratorSpec(
        target_type="cheatsheet",
        schema=CheatSheetModel,
        min_field="sections",
        min_count=2,
        prompt="""
You are producing a dense one-page reference sheet.

**Task**: Condense the source material into scannable sections.

**Each section needs**: a "heading" and "entries" - terse one-line facts,
formulas or definitions.

**Rules**:
1. Entries are lines, not paragraphs. No entry longer than ~120 characters.
2. Prefer formulas, thresholds, definitions and edge cases over prose.
3. Group by topic so it can be scanned under exam pressure.
4. Use LaTeX for every formula.
""",
    ),
    "mindmap": GeneratorSpec(
        target_type="mindmap",
        schema=MindMapModel,
        prompt="""
You are mapping the conceptual structure of the source material.

**Task**: Build a mind map as a tree.

**Each node needs**: a short "label" (a few words), an optional "detail", and
"children".

**Rules**:
1. The root is the subject of the material.
2. Produce 4-7 top-level branches, each with 2-4 leaves. The tree is exactly
   three levels deep - root, branch, leaf. Do not nest further.
3. Branches are concepts, not section titles - show how the ideas relate.
4. Leaves are concrete: a definition, a formula, an example.
5. Labels are at most six words. "detail" is ONE sentence under 140 characters -
   this renders inside a node on a canvas, not on a page.
""",
    ),
}


class ArtifactGenerator:
    """Turns a ``KnowledgeCore`` into a typed study artifact."""

    def __init__(self, llm: Optional[LLMProvider] = None):
        self.llm = llm or LLMFactory.get_provider()

    # -- prompt assembly ----------------------------------------------------

    @staticmethod
    def _with_instructions(prompt: str, instructions: Optional[str]) -> str:
        """
        Append user steering to a base prompt.

        Placed last and clearly delimited so it wins on conflict with the
        default prompt - that is the whole point of the assistant panel.
        """
        if not instructions or not instructions.strip():
            return prompt
        return (
            f"{prompt}\n\n"
            "--- USER INSTRUCTIONS (these take precedence over the defaults above) ---\n"
            f"{instructions.strip()}\n"
        )

    # -- validation ---------------------------------------------------------

    @staticmethod
    def validate(spec: GeneratorSpec, model: BaseModel) -> None:
        """
        Reject artifacts that are technically valid but useless.

        A three-question "quiz" parses fine and helps nobody, so a job that
        produces one is a failure, not a success.
        """
        data = model.model_dump() if hasattr(model, "model_dump") else dict(model)

        if spec.min_chars:
            body = data.get("body") or ""
            if len(body) < spec.min_chars:
                raise GenerationError(
                    f"{spec.target_type}: expected at least {spec.min_chars} characters, got {len(body)}"
                )

        if spec.min_field:
            items = data.get(spec.min_field) or []
            if len(items) < spec.min_count:
                raise GenerationError(
                    f"{spec.target_type}: expected at least {spec.min_count} "
                    f"{spec.min_field}, got {len(items)}"
                )

    # -- generation ---------------------------------------------------------

    async def generate(
        self,
        target_type: str,
        core: KnowledgeCore,
        instructions: Optional[str] = None,
    ) -> BaseModel:
        """Generate ``target_type`` from ``core``, honouring optional user instructions."""
        if target_type == "exam":
            return await self._build_exam(core, instructions)

        spec = SPECS.get(target_type)
        if spec is None:
            raise GenerationError(f"Unknown target type: {target_type}")

        prompt = self._with_instructions(spec.prompt, instructions)
        context = core.model_dump_json()

        logger.info("Generating %s (schema=%s)", target_type, spec.schema.__name__ if spec.schema else "markdown")
        result = await self.llm.generate_content_async(prompt=prompt, context=context, schema=spec.schema)

        model = self._coerce(spec, result, core)
        self.validate(spec, model)
        return model

    def _coerce(self, spec: GeneratorSpec, result: Any, core: KnowledgeCore) -> BaseModel:
        """Normalise whatever the provider returned into the spec's model."""
        if spec.schema is None:
            if not isinstance(result, str) or not result.strip():
                raise GenerationError(f"{spec.target_type}: expected markdown text, got {type(result).__name__}")
            body = result.strip()
            title = f"Notes: {core.title}"
            first_line = body.splitlines()[0] if body.splitlines() else ""
            if first_line.startswith("# "):
                title = first_line[2:].strip()
            return MarkdownNotesModel(title=title, format="markdown", body=body)

        if isinstance(result, spec.schema):
            return result
        if isinstance(result, dict):
            return spec.schema(**result)
        raise GenerationError(f"{spec.target_type}: unexpected result type {type(result).__name__}")

    # -- exam: multi-phase --------------------------------------------------

    async def _build_exam(
        self, core: KnowledgeCore, instructions: Optional[str] = None
    ) -> FinalExamModel:
        """
        Build an exam in two stages.

        The model first writes an assessment contract (discipline, style,
        grading philosophy), then writes each question batch against it. The
        batches are independent, so they run concurrently - which is where most
        of the wall-clock saving on exam generation comes from.
        """
        core_json = core.model_dump_json(indent=2)
        spec = await self._generate_exam_spec(core_json, instructions)

        batches = [("MCQ", 15, 3), ("Short Answer", 5, 5), ("Problem Set", 3, 10)]
        results = await asyncio.gather(
            *(self._question_batch(core_json, spec, q_type, count, points, instructions)
              for q_type, count, points in batches),
            return_exceptions=True,
        )

        questions: List[Dict[str, Any]] = []
        for (q_type, _, _), result in zip(batches, results):
            if isinstance(result, Exception):
                # One weak batch should not sink the exam; the count check below
                # decides whether what survived is still usable.
                logger.warning("Exam batch '%s' failed: %s", q_type, result)
                continue
            questions.extend(result)

        if len(questions) < 10:
            raise GenerationError(f"exam: expected at least 10 questions, got {len(questions)}")

        for index, question in enumerate(questions):
            question["id"] = f"Q-{index + 1}"

        return FinalExamModel(
            title=f"Final Exam: {core.title}",
            exam_spec=spec,
            instructions=f"({spec.instructions_tone}) {spec.exam_style}. Answer all questions.",
            rubric=spec.grading_philosophy,
            questions=questions,
        )

    async def _generate_exam_spec(self, core_json: str, instructions: Optional[str]) -> ExamSpec:
        prompt = self._with_instructions(
            """
You are an academic assessment designer.

**Task**: Define the assessment contract for the provided course material -
the discipline, the style of exam that suits it, the cognitive targets worth
testing, and how partial credit should be awarded.
""",
            instructions,
        )
        try:
            result = await self.llm.generate_content_async(prompt=prompt, context=core_json, schema=ExamSpec)
            if isinstance(result, ExamSpec):
                return result
            if isinstance(result, dict):
                return ExamSpec(**self._repair_spec(result))
        except Exception as exc:
            logger.warning("Exam spec generation failed (%s); using the default contract", exc)

        return ExamSpec(
            discipline="General",
            exam_style="Standard academic",
            cognitive_targets=["Recall", "Understanding", "Application"],
            grading_philosophy="Award partial credit for correct reasoning.",
            instructions_tone="Formal",
        )

    @staticmethod
    def _repair_spec(data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill in any contract field the model left out."""
        defaults = {
            "discipline": "General",
            "exam_style": "Standard academic",
            "cognitive_targets": ["Recall", "Analysis"],
            "grading_philosophy": "Points for correctness.",
            "instructions_tone": "Formal",
        }
        return {**defaults, **{k: v for k, v in data.items() if v}}

    async def _question_batch(
        self,
        core_json: str,
        spec: ExamSpec,
        q_type: str,
        count: int,
        points: int,
        instructions: Optional[str],
    ) -> List[Dict[str, Any]]:
        prompt = self._with_instructions(
            f"""
You are an examiner working to a fixed assessment contract.

**Assessment contract**
- Discipline: {spec.discipline}
- Style: {spec.exam_style}
- Grading philosophy: {spec.grading_philosophy}
- Cognitive targets: {", ".join(spec.cognitive_targets)}

**Task**: Write EXACTLY {count} questions of type "{q_type}", worth {points} points each.

**Rules**:
1. Exactly {count} questions - no more, no fewer.
2. Every question needs a "model_answer" and "grading_notes" that say where the
   marks are.
3. MCQ questions need four plausible options; other types have no options.
4. Use LaTeX for all mathematics.
""",
            instructions,
        )

        result = await self.llm.generate_content_async(prompt=prompt, context=core_json, schema=QuestionBatch)
        if isinstance(result, QuestionBatch):
            return [q.model_dump() for q in result.questions]
        if isinstance(result, dict):
            return result.get("questions", [])
        raise GenerationError(f"exam batch '{q_type}': unexpected result type {type(result).__name__}")

    # -- synchronous shims --------------------------------------------------
    # Kept so scripts and tests that predate the async rewrite still work.

    def _run_sync(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError("Use `await generator.generate(...)` from async code")

    def generate_quiz(self, core: KnowledgeCore) -> QuizModel:
        return self._run_sync(self.generate("quiz", core))

    def generate_exam(self, core: KnowledgeCore) -> FinalExamModel:
        return self._run_sync(self.generate("exam", core))

    def generate_notes(self, core: KnowledgeCore) -> MarkdownNotesModel:
        return self._run_sync(self.generate("notes", core))

    def generate_slides(self, core: KnowledgeCore) -> SlidesModel:
        return self._run_sync(self.generate("slides", core))

    def generate_flashcards(self, core: KnowledgeCore) -> FlashcardModel:
        return self._run_sync(self.generate("flashcards", core))
