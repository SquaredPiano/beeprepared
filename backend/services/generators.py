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

# Module-level model for structured output
class QuestionBatch(BaseModel):
    questions: List[ExamQuestion]

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
            
            # Use module-level QuestionBatch model
            result = self.llm.generate_content(
                prompt=prompt,
                context=core_json,
                schema=QuestionBatch
            )
            
            if result is None:
                logger.error(f"LLM returned None for {q_type} batch")
                return []
            
            if isinstance(result, QuestionBatch):
                logger.info(f"Successfully generated {len(result.questions)} {q_type} questions")
                return [q.model_dump() for q in result.questions]
            
            # Handle dict result
            if isinstance(result, dict) and 'questions' in result:
                logger.info(f"Converting dict result for {q_type}")
                return result.get('questions', [])
                
            logger.error(f"Unexpected result type for {q_type}: {type(result)}")
            return []

        except Exception as e:
            logger.error(f"Failed to generate batch {q_type}: {e}", exc_info=True)
            return []

    def generate_exam(self, core: KnowledgeCore) -> Optional[FinalExamModel]:
        if not self.llm: 
            logger.error("LLM not initialized for exam generation")
            return None
        
        logger.info("Starting exam generation...")
        core_json = core.model_dump_json(indent=2)
        
        spec = self._generate_exam_spec(core)
        if not spec:
            logger.info("Using default ExamSpec")
            spec = ExamSpec(
                discipline="General", 
                exam_style="Standard", 
                cognitive_targets=["Recall", "Understanding"],
                grading_philosophy="Standard points",
                instructions_tone="Standard"
            )

        all_questions = []
        # Phase 1: MCQs
        logger.info("Generating MCQ batch...")
        mcqs = self._generate_questions_batch(core_json, spec, "MCQ", 15, 3)
        all_questions.extend(mcqs)
        logger.info(f"Generated {len(mcqs)} MCQs")
        
        # Phase 2: Short Answer
        logger.info("Generating Short Answer batch...")
        shorts = self._generate_questions_batch(core_json, spec, "Short Answer", 5, 5)
        all_questions.extend(shorts)
        logger.info(f"Generated {len(shorts)} short answers")
        
        # Phase 3: Problem Sets
        logger.info("Generating Problem Set batch...")
        problems = self._generate_questions_batch(core_json, spec, "Problem Set", 3, 10)
        all_questions.extend(problems)
        logger.info(f"Generated {len(problems)} problem sets")
        
        if not all_questions:
            logger.error("No questions generated for exam")
            return None

        logger.info(f"Total questions generated: {len(all_questions)}")
        
        # Fix IDs
        for i, q in enumerate(all_questions):
            q["id"] = f"Q-{i+1}"

        try:
            exam = FinalExamModel(
                title=f"Final Exam: {core.title}",
                exam_spec=spec,
                instructions=f"({spec.instructions_tone}) {spec.exam_style}. Answer all questions.",
                rubric=spec.grading_philosophy,
                questions=all_questions
            )
            logger.info("Successfully created FinalExamModel")
            return exam
        except Exception as e:
            logger.error(f"Failed to assemble FinalExamModel: {e}", exc_info=True)
            return None

    def generate_quiz(self, core: KnowledgeCore) -> Optional[QuizModel]:
        if not self.llm: 
            logger.error("LLM not initialized for quiz generation")
            return None
        
        prompt = """
        You are an expert Examiner creating a quiz.
        
        **Task**: Generate 10-15 quiz questions based on the provided course material.
        
        **Each question must have**:
        - "id": Unique identifier (e.g., "Q1", "Q2")
        - "text": The question text (use LaTeX for math, e.g., $x^2$)
        - "type": Either "True/False" or "MCQ"
        - "options": List of options (["True", "False"] for T/F, or ["A", "B", "C", "D"] for MCQ)
        - "correct_answer_index": Index of the correct option (0-based)
        - "explanation": Why this answer is correct
        - "topic_focus": The specific concept being tested
        
        **Rules**:
        1. Mix True/False and MCQ questions
        2. Cover the most important concepts
        3. Make questions clear and unambiguous
        4. Use LaTeX for all mathematical expressions
        
        **Output**: A JSON object with "title" and "questions" array.
        """
        
        try:
            logger.info("Starting quiz generation...")
            result = self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json(),
                schema=QuizModel
            )
            
            if result is None:
                logger.error("LLM returned None for quiz")
                return None
                
            if isinstance(result, QuizModel):
                logger.info(f"Successfully generated quiz with {len(result.questions)} questions")
                return result
            
            if isinstance(result, dict):
                logger.info("Converting dict result to QuizModel")
                return QuizModel(**result)
                
            logger.error(f"Unexpected result type: {type(result)}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to generate Quiz: {e}", exc_info=True)
            return None

    def generate_flashcards(self, core: KnowledgeCore) -> Optional[FlashcardModel]:
        if not self.llm: 
            logger.error("LLM not initialized for flashcard generation")
            return None
        
        prompt = """
        You are an expert Tutor creating study flashcards.
        
        **Task**: Generate 15-20 flashcards based on the provided course material.
        
        **Each flashcard must have**:
        - "front": The question or concept (use LaTeX for math, e.g., $x^2$)
        - "back": The answer or definition (use LaTeX for math)
        - "hint": Optional hint to help recall (can be null)
        
        **Rules**:
        1. Cover the most important concepts from the material
        2. Make questions clear and unambiguous
        3. Keep answers concise but complete
        4. Use LaTeX notation for all mathematical expressions
        
        **Output**: A JSON object with a "cards" array containing the flashcards.
        """
        
        try:
            logger.info("Starting flashcard generation...")
            result = self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json(),
                schema=FlashcardModel
            )
            
            if result is None:
                logger.error("LLM returned None for flashcards")
                return None
                
            if isinstance(result, FlashcardModel):
                logger.info(f"Successfully generated {len(result.cards)} flashcards")
                return result
            
            # If we got a dict, try to parse it
            if isinstance(result, dict):
                logger.info("Converting dict result to FlashcardModel")
                return FlashcardModel(**result)
                
            logger.error(f"Unexpected result type: {type(result)}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to generate Flashcards: {e}", exc_info=True)
            return None

    def generate_notes(self, core: KnowledgeCore) -> Optional[MarkdownNotesModel]:
        if not self.llm: 
            logger.error("LLM not initialized for notes generation")
            return None
        
        prompt = """
        You are an expert Academic Note-Taker.
        
        **Task**: Generate detailed study notes in Markdown format based on the provided material.
        
        **Requirements**:
        1. Start with a heading using # syntax
        2. Organize content into clear sections with ## and ### headings
        3. Use bullet points for key concepts
        4. Use LaTeX for ALL mathematical formulas ($...$ for inline, $$...$$ for block)
        5. Include definitions, examples, and key takeaways
        
        **Output**: Pure Markdown text (not JSON).
        """
        
        try:
            logger.info("Starting notes generation...")
            # No schema -> returns string
            text = self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json()
            )
            
            if not text:
                logger.error("LLM returned empty response for notes")
                return None
                
            if not isinstance(text, str):
                logger.error(f"Expected string but got {type(text)}")
                return None
            
            logger.info(f"Generated notes with {len(text)} characters")
            
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
            logger.error(f"Failed to generate Notes: {e}", exc_info=True)
            return None

    def generate_slides(self, core: KnowledgeCore) -> Optional[SlidesModel]:
        if not self.llm: 
            logger.error("LLM not initialized for slides generation")
            return None
        
        prompt = """
        You are an expert Content Designer creating a presentation.
        
        **Task**: Generate 10-12 presentation slides based on the provided course material.
        
        **Each slide must have**:
        - "heading": Slide headline
        - "main_idea": One sentence summary
        - "bullet_points": 3-5 brief bullet points
        - "visual_cue": Description for image/chart
        - "speaker_notes": What the presenter should say
        
        **Rules**:
        1. Cover the most important concepts
        2. Keep slides concise and scannable
        3. Use LaTeX for mathematical expressions
        4. Include a title slide and conclusion slide
        
        **Output**: A JSON object with "title", "audience_level", and "slides" array.
        """
        
        try:
            logger.info("Starting slides generation...")
            result = self.llm.generate_content(
                prompt=prompt,
                context=core.model_dump_json(),
                schema=SlidesModel
            )
            
            if result is None:
                logger.error("LLM returned None for slides")
                return None
                
            if isinstance(result, SlidesModel):
                logger.info(f"Successfully generated {len(result.slides)} slides")
                return result
            
            if isinstance(result, dict):
                logger.info("Converting dict result to SlidesModel")
                return SlidesModel(**result)
                
            logger.error(f"Unexpected result type: {type(result)}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to generate Slides: {e}", exc_info=True)
            return None
