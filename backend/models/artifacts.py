from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field

# --- 0. Exam Specification (The Assessment Contract) ---
class ExamSpec(BaseModel):
    discipline: Literal["Writing", "Philosophy", "Math", "Physics", "CS", "General"] = Field(description="The academic discipline")
    exam_style: str = Field(description="The style of the exam (e.g., 'Analytic', 'Problem-Solving', 'Creative').")
    cognitive_targets: List[str] = Field(description="Specific learning outcomes to test (e.g., 'Synthesis', 'Application').")
    grading_philosophy: str = Field(description="How partial credit should be awarded.")
    instructions_tone: str = Field(description="Tone of the instructions (e.g., 'Formal', 'Encouraging').")

# --- 1. Final Exam Model ---
class ExamQuestion(BaseModel):
    id: str = Field(description="Unique identifier for the question (e.g., 'Q1')")
    text: str = Field(description="The question text. Use LaTeX for math (e.g., $\int x dx$).")
    type: Literal['MCQ', 'Short Answer', 'Problem Set'] = Field(description="Type of question")
    options: Optional[List[str]] = Field(description="Options for MCQ, null for others")
    points: int = Field(description="Point value for this question")
    # New V2 Fields
    model_answer: str = Field(description="The ideal correct answer.")
    grading_notes: str = Field(description="Criteria for awarding full vs partial credit.")

class FinalExamModel(BaseModel):
    title: str = Field(description="Title of the Exam")
    exam_spec: Optional[ExamSpec] = Field(None, description="The specification used to generate this exam.")
    instructions: Optional[str] = Field(description="General instructions for the students")
    questions: Optional[List[ExamQuestion]] = Field(description="List of exam questions")
    rubric: Optional[str] = Field(description="Grading rubric and solution key overview")



# --- 2. Quiz Model ---
class QuizQuestion(BaseModel):
    id: str = Field(description="Unique ID")
    text: str = Field(description="Question text")
    type: Literal['True/False', 'MCQ'] = Field(description="Quiz question type")
    options: List[str] = Field(description="List of options (e.g., ['True', 'False'] or ['A', 'B', 'C', 'D'])")
    correct_answer_index: int = Field(description="Index of the correct option (0-based)")
    explanation: str = Field(description="Why this answer is correct. Critical for learning.")
    topic_focus: str = Field(description="The specific concept this question tests")

class QuizModel(BaseModel):
    title: str = Field(description="Title of the Quiz")
    questions: List[QuizQuestion] = Field(description="List of quiz questions")

# --- 3. Flashcards Model ---
class Flashcard(BaseModel):
    front: str = Field(description="Concept or Question. Use LaTeX for math.")
    back: str = Field(description="Definition or Answer. Use LaTeX for math.")
    hint: Optional[str] = Field(None, description="Optional hint for the user")
    source_reference: str = Field(description="Where in the material this comes from")

class FlashcardModel(BaseModel):
    cards: List[Flashcard] = Field(description="List of flashcards")

# --- 4. Notes Model ---
class NoteSection(BaseModel):
    heading: str = Field(description="Section heading")
    key_points: List[str] = Field(description="List of bullet points")
    content_block: str = Field(description="Detailed content in Markdown")
    key_terms: List[str] = Field(description="List of import terms in this section")
    callouts: List[str] = Field(description="Important warnings, formulas, or tips")

class NotesModel(BaseModel):
    title: str = Field(description="Title of the notes document")
    sections: List[NoteSection] = Field(description="List of note sections")

# --- 5. Slides Model ---
class Slide(BaseModel):
    heading: str = Field(description="Slide headline")
    main_idea: str = Field(description="One sentence summary of the slide")
    bullet_points: List[str] = Field(description="3-5 brief bullet points")
    visual_cue: str = Field(description="Prompt for image generation or chart description")
    speaker_notes: str = Field(description="What the speaker should say for this slide")

class SlidesModel(BaseModel):
    title: str = Field(description="Presentation Title")
    audience_level: str = Field(description="Target audience (e.g., 'Beginner', 'Advanced')")
    slides: List[Slide] = Field(description="List of slides")
