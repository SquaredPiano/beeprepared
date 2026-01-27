import logging
import json
from typing import Optional, Dict, Any, Type, List
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.core.services.llm_factory import LLMFactory
from backend.core.llm_interface import LLMProvider

from backend.models.artifacts import (
    FinalExamModel, QuizModel, FlashcardModel, NotesModel, MarkdownNotesModel, SlidesModel, ExamQuestion, ExamSpec
)
from backend.core.knowledge_core import KnowledgeCore

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class ArtifactGenerator:
    def __init__(self):
        self._setup_llm()

    def _setup_llm(self):
        try:
            self.llm = LLMFactory.get_provider()
            logger.info(f"ArtifactGenerator using provider: {type(self.llm).__name__}")
        except Exception as e:
            logger.error(f"Failed to initialize LLM Provider: {e}")
            self.llm = None

    def _repair_spec(self, data: Any) -> Any:
        # Default fallbacks if keys missing
        if isinstance(data, dict):
            if "discipline" not in data: data["discipline"] = "General"
            if "exam_style" not in data: data["exam_style"] = "Standard Academic"
            if "cognitive_targets" not in data: data["cognitive_targets"] = ["Recall", "Analysis"]
            if "grading_philosophy" not in data: data["grading_philosophy"] = "Points for correctness."
            if "instructions_tone" not in data: data["instructions_tone"] = "Formal"
        return data

    def _generate_exam_spec(self, core: KnowledgeCore) -> Optional[ExamSpec]:
        """Call 0: Define the Assessment Contract."""
        if not self.llm: return None
        
        # We assume the provider handles context concatenation if we pass it as context
        # But here logic passes list [prompt, core_json]. 
        # Interface expects prompt, context=str.
        
        core_str = core.model_dump_json(indent=2)
        
        prompt = """
        You are an expert Academic Assessment Designer.
        **Task**: Define the Exam Specification (Assessment Contract) for the provided course material.
        **Goal**: Determine the styling, difficulty, and pedagogical targets suitable for this specific subject.
        """
        
        try:
            logger.info("Generating Exam Specification (Call 0)...")
            # Use structured output
            result = self.llm.generate_content(
                prompt=prompt,
                context=core_str,
                schema=ExamSpec
            )
            
            if isinstance(result, ExamSpec):
                return result
            # Fallback if provider returns dict
            return ExamSpec(**self._repair_spec(result)) if result else None
            
        except Exception as e:
            logger.error(f"Failed to generate ExamSpec: {e}")
            return None

    def _generate_questions_batch(self, core_json: str, spec: ExamSpec, q_type: str, count: int, points: int) -> List[Dict[str, Any]]:
        """
        Generates a specific batch of questions (Sync).
        Returns list of dicts.
        """
        if not self.llm: return []

        prompt = f"""
        You are an expert Examiner following a specific Assessment Contract.
        
        **Assessment Contract**:
        - Discipline: {spec.discipline}
        - Style: {spec.exam_style}
        - Grading Philosophy: {spec.grading_philosophy}
        
        **Task**: Generate EXACTLY {count} questions of type "{q_type}".
        
        **Rules**:
        1. **Count**: List exactly {count} questions.
        2. **Type**: "{q_type}".
        3. **Points**: {points} points each.
        4. **Alignment**: Questions must match the cognitive targets: {", ".join(spec.cognitive_targets)}.
        5. **Rigorous Answers**: You MUST provide a 'model_answer' and 'grading_notes' for every question.
        6. **Formatting**: Use LaTeX for ALL mathematical notation. Wrap inline math in $...$ (e.g. $E=mc^2$) and block math in $$...$$.
        
        **Output Format**:
        Return a raw JSON list. Each object:
        - "id": "1", ...
        - "text": "Question..."
        - "type": "{q_type}"
        - "options": ["A", "B",...] (MCQ only)
        - "model_answer": "The ideal complete response..."
        - "grading_notes": "1 pt for X, 2 pts for Y..."
        - "points": {points}
        """

        try:
            logger.info(f"Generating batch: {count} x {q_type}...")
            
            # Since 'List[Dict]' isn't a pydantic model, needed for schema, we might get raw JSON text
            # Or define a wrapper model like BatchResponse(questions: List[ExamQuestion])
            
            # Let's try raw JSON generation by *not* passing schema but asking for JSON in prompt (Vertex handles response_mime_type if set manually in provider, but interface hides it)
            # Actually, `LLMProvider` interface implementation handles Pydantic schema.
            # If I want raw JSON list, I should define a wrapper model.
            
            class QuestionBatch(BaseModel):
                questions: List[ExamQuestion]

            result = self.llm.generate_content(
                prompt=prompt,
                context=core_json,
                schema=QuestionBatch
            )
            
            if isinstance(result, QuestionBatch):
                # Convert back to list of dicts for processing
                return [q.model_dump() for q in result.questions]
                
            return []

        except Exception as e:
            logger.error(f"Failed to generate batch {q_type}: {e}")
            return []

    def generate_exam(self, core: KnowledgeCore) -> Optional[FinalExamModel]:
        if not self.llm: return None
        core_json = core.model_dump_json(indent=2)
        
        spec = self._generate_exam_spec(core)
        if not spec:
            spec = ExamSpec(
                discipline="General", 
                exam_style="Standard", 
                cognitive_targets=["Recall", "Understanding"],
                grading_philosophy="Standard points",
                instructions_tone="Standard"
            )

        all_questions = []
        # Phase 1: MCQs
        mcqs = self._generate_questions_batch(core_json, spec, "MCQ", 15, 3)
        all_questions.extend(mcqs)
        # Phase 2: Short Answer
        shorts = self._generate_questions_batch(core_json, spec, "Short Answer", 5, 5)
        all_questions.extend(shorts)
        # Phase 3: Problem Sets
        problems = self._generate_questions_batch(core_json, spec, "Problem Set", 3, 10)
        all_questions.extend(problems)
        
        if not all_questions:
            return None

        # Fix IDs
        for i, q in enumerate(all_questions):
            q["id"] = f"Q-{i+1}"

        try:
            return FinalExamModel(
                title=f"Final Exam: {core.title}",
                exam_spec=spec,
                instructions=f"({spec.instructions_tone}) {spec.exam_style}. Answer all questions.",
                rubric=spec.grading_philosophy,
                questions=all_questions
            )
        except Exception as e:
            logger.error(f"Failed to assemble FinalExamModel: {e}")
            return None

    def generate_quiz(self, core: KnowledgeCore) -> Optional[QuizModel]:
        if not self.llm: return None
        prompt = """
        You are an expert Examiner.
        **Task**: Generate a QuizModel based on the provided content (10-15 questions).
        **Formatting**: Use LaTeX for all math ($x^2$).
        """
        try:
            return self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json(),
                schema=QuizModel
            )
        except Exception as e:
            logger.error(f"Failed to generate Quiz: {e}")
            return None

    def generate_flashcards(self, core: KnowledgeCore) -> Optional[FlashcardModel]:
        if not self.llm: return None
        prompt = """
        You are an expert Tutor.
        **Task**: Generate a FlashcardModel (15-20 cards).
        **Formatting**: Use LaTeX for all math ($x^2$).
        """
        try:
            return self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json(),
                schema=FlashcardModel
            )
        except Exception as e:
            logger.error(f"Failed to generate Flashcards: {e}")
            return None

    def generate_notes(self, core: KnowledgeCore) -> Optional[MarkdownNotesModel]:
        if not self.llm: return None
        prompt = """
        You are an expert Academic Note-Taker.
         **Task**: Generate detailed study notes in Markdown format.
         **Output**: Pure Markdown text.
         **Formatting**: Use LaTeX for ALL mathematical formulas ($...$ or $$...$$).
        """
        try:
            # No schema -> returns string
            text = self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json()
            )
            if not text or not isinstance(text, str): 
                return None
            
            title = f"Notes: {core.title}"
            lines = text.split('\n')
            if lines and lines[0].startswith('# '):
                title = lines[0][2:].strip()

            return MarkdownNotesModel(
                title=title,
                format="markdown",
                body=text
            )
        except Exception as e:
            logger.error(f"Failed to generate Notes: {e}")
            return None

    def generate_slides(self, core: KnowledgeCore) -> Optional[SlidesModel]:
        if not self.llm: return None
        prompt = """
        You are an expert Content Designer.
        **Task**: Generate a SlidesModel (10-12 slides).
        """
        try:
            return self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json(),
                schema=SlidesModel
            )
        except Exception as e:
            logger.error(f"Failed to generate Slides: {e}")
            return None
