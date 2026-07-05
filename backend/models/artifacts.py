"""The shape of every study artifact the generator can produce."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field


class ExamSpec(BaseModel):
    """The assessment contract an exam is written against."""

    discipline: Literal["Writing", "Philosophy", "Math", "Physics", "CS", "General"]
    exam_style: str = Field(description="Analytic, problem-solving, creative, and so on")
    cognitive_targets: List[str] = Field(description="Learning outcomes under test")
    grading_philosophy: str = Field(description="How partial credit is awarded")
    instructions_tone: str = Field(description="Formal, encouraging, and so on")


class ExamQuestion(BaseModel):
    id: str
    text: str = Field(description="The question. LaTeX for mathematics")
    type: Literal["MCQ", "Short Answer", "Problem Set"]
    options: Optional[List[str]] = Field(description="Choices for MCQ, null otherwise")
    points: int
    model_answer: str = Field(description="The ideal complete response")
    grading_notes: str = Field(description="Where the marks are")


class FinalExamModel(BaseModel):
    title: str
    exam_spec: Optional[ExamSpec] = None
    instructions: Optional[str] = None
    questions: List[ExamQuestion] = Field(default_factory=list)
    rubric: Optional[str] = None


class QuizQuestion(BaseModel):
    id: str
    text: str
    type: Literal["True/False", "MCQ"]
    options: List[str]
    correct_answer_index: int = Field(description="Zero-based index into options")
    explanation: str = Field(description="Why that answer is right")
    topic_focus: str = Field(description="The concept under test")


class QuizModel(BaseModel):
    title: str
    questions: List[QuizQuestion]


class Flashcard(BaseModel):
    front: str = Field(description="Prompt or question")
    back: str = Field(description="Answer or definition")
    hint: Optional[str] = None
    source_reference: Optional[str] = None


class FlashcardModel(BaseModel):
    cards: List[Flashcard]


class NotesModel(BaseModel):
    """Study notes held as Markdown."""

    title: str
    format: str = "markdown"
    body: str


class Slide(BaseModel):
    heading: str
    main_idea: str = Field(description="One sentence summary")
    bullet_points: List[str]
    visual_cue: str = Field(description="What to draw on this slide")
    speaker_notes: str


class SlidesModel(BaseModel):
    title: str
    audience_level: str
    slides: List[Slide]


class StudyGuideModel(BaseModel):
    """A revision plan for a single study session."""

    title: str
    estimated_minutes: int
    objectives: List[str] = Field(description="Most important first")
    body: str = Field(description="Markdown, ordered by dependency")
    checklist: List[str] = Field(description="Self-check questions")


class CheatSheetSection(BaseModel):
    heading: str
    entries: List[str] = Field(description="Terse one-line facts or formulas")


class CheatSheetModel(BaseModel):
    """A dense single-page reference, optimised for scanning."""

    title: str
    sections: List[CheatSheetSection]


class MindMapLeaf(BaseModel):
    label: str = Field(description="At most six words")
    detail: Optional[str] = Field(None, description="One sentence under 140 characters")


class MindMapBranch(BaseModel):
    label: str = Field(description="At most six words")
    detail: Optional[str] = Field(None, description="One sentence under 140 characters")
    children: List[MindMapLeaf] = Field(default_factory=list)


class MindMapRoot(BaseModel):
    label: str = Field(description="The subject of the material")
    detail: Optional[str] = None
    children: List[MindMapBranch] = Field(default_factory=list)


class MindMapModel(BaseModel):
    """
    A concept map fixed at three levels.

    Depth is expressed with distinct types rather than a self-referencing node,
    because a recursive schema gives the model no bound to stop at.
    """

    title: str
    root: MindMapRoot


ARTIFACT_MODELS: Dict[str, Type[BaseModel]] = {
    "quiz": QuizModel,
    "exam": FinalExamModel,
    "notes": NotesModel,
    "slides": SlidesModel,
    "flashcards": FlashcardModel,
    "study_guide": StudyGuideModel,
    "cheatsheet": CheatSheetModel,
    "mindmap": MindMapModel,
}

GENERATED_TYPES = frozenset(ARTIFACT_MODELS)

SOURCE_TYPES = frozenset({"youtube", "audio", "video", "pdf", "pptx", "md"})
