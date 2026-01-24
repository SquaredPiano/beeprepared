import os
import logging
import json
from typing import Optional, Dict, Any, Type, List
from pydantic import BaseModel
import google.generativeai as genai
from dotenv import load_dotenv

from backend.models.artifacts import (
    FinalExamModel, QuizModel, FlashcardModel, NotesModel, SlidesModel, ExamQuestion, ExamSpec
)
from backend.knowledge_core import KnowledgeCore

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class ArtifactGenerator:
    def __init__(self, model_name: str = 'gemini-flash-latest'):
        """
        Initialize the ArtifactGenerator.
        
        Args:
            model_name: The Gemini model to use. Defaults to 'gemini-flash-latest'.
        """
        self._setup_gemini(model_name)

    def _setup_gemini(self, model_name: str):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel(model_name)
                logger.info(f"ArtifactGenerator initialized with model: {model_name}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.model = None
        else:
            logger.warning("GEMINI_API_KEY not found.")
            self.model = None

    def _repair_json(self, data: Any, artifact_type: str) -> Any:
        """
        Attempts to repair common JSON structural issues from Gemini.
        """
        if artifact_type == "Final Exam":
            # Fix Questions (Generic fix if full exam was generated at once)
            if "questions" in data and isinstance(data["questions"], list):
                for q in data["questions"]:
                    self._normalize_question(q)
            
            # Fix top-level fields
            if "rubric" not in data: data["rubric"] = "See solutions."
            if "instructions" not in data: data["instructions"] = "Answer all questions."
            if "title" not in data: data["title"] = "Generated Exam"

        return data

    def _normalize_question(self, q: Dict[str, Any]) -> None:
        """Helper to normalize a single question dictionary in-place."""
        # 1. Normalize 'type'
        q_type = str(q.get("type", "")).lower()
        if "multiple" in q_type or "mcq" in q_type:
            q["type"] = "MCQ"
        elif "short" in q_type:
            q["type"] = "Short Answer"
        elif "problem" in q_type:
            q["type"] = "Problem Set"
        else:
            q["type"] = "Short Answer" # Default fallback

        # 2. Fix 'id' to be string
        if "id" in q:
            q["id"] = str(q["id"])
        else:
            q["id"] = "0"

        # 3. Fix 'options' being objects or missing
        if "options" in q and isinstance(q["options"], list):
            new_opts = []
            for opt in q["options"]:
                if isinstance(opt, dict):
                    new_opts.append(opt.get("value", str(opt)))
                else:
                    new_opts.append(str(opt))
            q["options"] = new_opts
        else:
            # Ensure options is None if not MCQ, or empty list if it is
            if q["type"] == "MCQ":
                q["options"] = []
            else:
                q["options"] = None

        # 4. Fix missing required fields
        if "text" not in q: q["text"] = "Question text missing."
        if "points" not in q: q["points"] = 5
        if "model_answer" not in q: q["model_answer"] = q.get("correct_answer", "See Grading Notes")
        if "grading_notes" not in q: q["grading_notes"] = "Full credit for correct answer."

    def _repair_spec(self, data: Any) -> Any:
        # Default fallbacks if keys missing
        if "discipline" not in data: data["discipline"] = "General"
        if "exam_style" not in data: data["exam_style"] = "Standard Academic"
        if "cognitive_targets" not in data: data["cognitive_targets"] = ["Recall", "Analysis"]
        if "grading_philosophy" not in data: data["grading_philosophy"] = "Points for correctness."
        if "instructions_tone" not in data: data["instructions_tone"] = "Formal"
        return data

    def _generate_exam_spec(self, core: KnowledgeCore) -> Optional[ExamSpec]:
        """Call 0: Define the Assessment Contract."""
        if not self.model: return None
        
        core_json = core.model_dump_json(indent=2)
        prompt = """
        You are an expert Academic Assessment Designer.
        
        **Task**: Define the Exam Specification (Assessment Contract) for the provided course material.
        
        **Goal**: Determine the styling, difficulty, and pedagogical targets suitable for this specific subject.
        - If it's Philosophy, focus on analysis and synthesis.
        - If it's Math/Science, focus on problem-solving and application.
        
        **Output**: Return strictly valid JSON matching the ExamSpec schema.
        - discipline: One of ["Writing", "Philosophy", "Math", "Physics", "CS", "General"]
        - exam_style: string
        - cognitive_targets: list of strings
        - grading_philosophy: string
        - instructions_tone: string
        """
        
        try:
            logger.info("Generating Exam Specification (Call 0)...")
            response = self.model.generate_content(
                [prompt, core_json],
                generation_config=genai.GenerationConfig(response_mime_type="application/json", temperature=0.3)
            )
            if response.text:
                data = json.loads(response.text)
                data = self._repair_spec(data)
                return ExamSpec(**data)
        except Exception as e:
            logger.error(f"Failed to generate ExamSpec: {e}")
            return None

    def _generate_questions_batch(self, core_json: str, spec: ExamSpec, q_type: str, count: int, points: int) -> List[Dict[str, Any]]:
        """
        Generates a specific batch of questions using the ExamSpec for alignment.
        """
        if not self.model: return []

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
        
        **CRITICAL INSTRUCTIONS FOR MATH & SCIENCE**:
        - Use strict LaTeX for all math: $\\alpha$, $$\\int x dx$$.
        - No Unicode math.
        
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
            logger.info(f"Generating batch: {count} x {q_type} (Spec: {spec.discipline})...")
            response = self.model.generate_content(
                [prompt, core_json],
                generation_config=genai.GenerationConfig(response_mime_type="application/json", temperature=0.3),
                request_options={"timeout": 90}
            )
            
            if response.text:
                data = json.loads(response.text)
                if isinstance(data, dict):
                    for key in data:
                        if isinstance(data[key], list):
                            data = data[key]
                            break
                
                if isinstance(data, list):
                    for i, q in enumerate(data):
                        self._normalize_question(q)
                        q["type"] = q_type
                        q["id"] = f"{q_type[0]}-{i+1}"
                    return data
            return []

        except Exception as e:
            logger.error(f"Failed to generate batch {q_type}: {e}")
            return []

    def generate_exam(self, core: KnowledgeCore) -> Optional[FinalExamModel]:
        """
        Generation V2: Spec-Driven Chained Generation.
        """
        if not self.model: return None
        core_json = core.model_dump_json(indent=2)
        
        # Step 0: Generate Spec
        spec = self._generate_exam_spec(core)
        if not spec:
            # Fallback spec
            spec = ExamSpec(
                discipline="General", 
                exam_style="Standard", 
                cognitive_targets=["Recall", "Understanding"],
                grading_philosophy="Standard points",
                instructions_tone="Standard"
            )
            logger.warning("Using fallback ExamSpec.")

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
        
        total_q = len(all_questions)
        logger.info(f"Total questions generated: {total_q}")

        if total_q == 0:
            return None

        # Assemble Final Exam
        try:
            exam_data = {
                "title": f"Final Exam: {core.title}",
                "exam_spec": spec,
                "instructions": f"({spec.instructions_tone} Tone) {spec.exam_style} Exam. Please answer all questions.",
                "rubric": f"Grading Philosophy: {spec.grading_philosophy}. See individual grading notes.",
                "questions": all_questions
            }
            return FinalExamModel(**exam_data)
        except Exception as e:
            logger.error(f"Failed to assemble FinalExamModel: {e}")
            return None

    def _generate_artifact(self, knowledge_core: KnowledgeCore, target_model: Type[BaseModel], artifact_type: str) -> Optional[BaseModel]:
        """
        Generic method to generate simpler artifacts (Quiz, Cards, Notes).
        """
        if not self.model:
            logger.error("Gemini model not initialized.")
            return None

        # Serialize Knowledge Core to JSON string for context
        core_json = knowledge_core.model_dump_json(indent=2)

        prompt = f"""
        You are an expert Educational Content Generator.
        
        **Source Material**: Use the provided Knowledge Core JSON as your absolute Source of Truth.
        **Task**: Generate a {artifact_type} object based on this knowledge.
        
        **CRITICAL INSTRUCTIONS FOR MATH & SCIENCE**:
        - If the subject involves Math, Physics, Chemistry, or any Science:
        - You MUST use strict LaTeX formatting for all formulas, equations, and mathematical symbols.
        - Enclose inline math in single dollars: $\\alpha$
        - Enclose block math in double dollars: $$\\int_0^\\infty x dx$$
        - Do NOT use Unicode mathematical symbols (e.g., do not use "∫", use "$\\int$").
        
        **Output Format**:
        - Return strictly valid JSON that matches the schema for {artifact_type}.
        - Do not include markdown code blocks (e.g. ```json). Just the raw JSON.
        """

        try:
            logger.info(f"Generating {artifact_type}...")
            # Use json mode without schema (not supported in this SDK)
            response = self.model.generate_content(
                [prompt, core_json],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                ),
                request_options={"timeout": 60}
            )
            
            if response.text:
                # Log raw text for debugging
                logger.debug(f"Raw Gemini response: {response.text[:500]}...")
                try:
                    data = json.loads(response.text)
                    # Repair JSON structure before validation (only needed for generic path if needed)
                    # For strict types we might need specific repair logic, but for now we trust the generic prompt
                    # or add specific repairs if Quiz/Flashcards fail.
                    # We can reuse the generic repair for top-level fields if we want.
                    return target_model(**data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON received: {e}")
                    return None
            else:
                logger.error(f"Empty response for {artifact_type}")
                return None

        except Exception as e:
            logger.error(f"Failed to generate {artifact_type}: {e}")
            return None

    def generate_quiz(self, core: KnowledgeCore) -> Optional[QuizModel]:
        """Generates a comprehensive Quiz with explanations."""
        if not self.model: return None
        core_json = core.model_dump_json(indent=2)
        prompt = """
        You are an expert Examiner.
        **Task**: Generate a QuizModel based on the provided content.
        **Requirements**:
        - Generate 10-15 questions.
        - Mix 'MCQ' and 'True/False' types.
        - **Structure**:
            - "title": "Quiz Title"
            - "questions": List of objects:
                - "id": "1"
                - "text": "Question Text"
                - "type": "MCQ" or "True/False"
                - "options": ["A", "B", "C", "D"] (List of strings only!)
                - "correct_answer_index": int (0-based index of correct option)
                - "explanation": "Detailed explanation..."
                - "topic_focus": "Concept being tested"
        - Use strict LaTeX for math strings ($\int$).
        - **CRITICAL JSON SYNTAX**: You MUST double-escape backslashes in JSON strings. Use "\\\\" for backslashes (e.g. "\\\\int", not "\\int").
        - Return strictly valid JSON.
        """
        try:
            logger.info("Generating Quiz...")
            response = self.model.generate_content([prompt, core_json], generation_config=genai.GenerationConfig(response_mime_type="application/json"))
            if response.text:
                data = json.loads(response.text)
                if "questions" not in data and isinstance(data, list):
                    data = {"title": f"Quiz: {core.title}", "questions": data}
                if "title" not in data: data["title"] = f"Quiz: {core.title}"
                return QuizModel(**data)
        except Exception as e:
            logger.error(f"Failed to generate Quiz: {e}")
        return None

    def generate_flashcards(self, core: KnowledgeCore) -> Optional[FlashcardModel]:
        """Generates Flashcards for active recall."""
        if not self.model: return None
        core_json = core.model_dump_json(indent=2)
        prompt = """
        You are an expert Tutor.
        **Task**: Generate a FlashcardModel based on the provided content.
        **Requirements**:
        - Generate 15-20 high-quality flashcards.
        - **Structure**:
            - "cards": List of objects:
                - "front": "Concept or Question" (Concise)
                - "back": "Definition or Answer" (Clear, formatted)
                - "hint": "Optional hint" or null
                - "source_reference": "Lecture timestamp or section name"
        - Use strict LaTeX for math.
        - **CRITICAL JSON SYNTAX**: You MUST double-escape backslashes in JSON strings. Use "\\\\" for backslashes (e.g. "\\\\int", not "\\int").
        - Return strictly valid JSON.
        """
        try:
            logger.info("Generating Flashcards...")
            response = self.model.generate_content([prompt, core_json], generation_config=genai.GenerationConfig(response_mime_type="application/json"))
            if response.text:
                data = json.loads(response.text)
                if "cards" not in data and isinstance(data, list):
                    data = {"cards": data} # FlashcardModel doesn't have title? Wait, checking schema.
                # Schema: cards: List[Flashcard]. No title?
                # Let's check schema. FlashcardModel has only cards?
                # Previous view showed: class FlashcardModel(BaseModel): cards: List[Flashcard].
                return FlashcardModel(**data)
        except Exception as e:
            logger.error(f"Failed to generate Flashcards: {e}")
        return None

    def generate_notes(self, core: KnowledgeCore) -> Optional[NotesModel]:
        """Generates detailed Study Notes in Markdown."""
        if not self.model: return None
        core_json = core.model_dump_json(indent=2)
        prompt = """
        You are an expert Academic Note-Taker.
        **Task**: Generate a NotesModel.
        **Requirements**:
        - **Structure**:
            - "title": "Notes Title"
            - "sections": List of objects:
                - "heading": "Section Title"
                - "key_points": ["Point 1", "Point 2"]
                - "content_block": "Detailed markdown content..."
                - "key_terms": ["Term 1", "Term 2"]
                - "callouts": ["Important: ...", "Formula: ..."]
        - Use strict LaTeX for math.
        - **CRITICAL JSON SYNTAX**: You MUST double-escape backslashes in JSON strings. Use "\\\\" for backslashes (e.g. "\\\\int", not "\\int").
        - Return strictly valid JSON.
        """
        try:
            logger.info("Generating Notes...")
            response = self.model.generate_content([prompt, core_json], generation_config=genai.GenerationConfig(response_mime_type="application/json"))
            if response.text:
                data = json.loads(response.text)
                if "title" not in data: data["title"] = f"Notes: {core.title}"
                return NotesModel(**data)
        except Exception as e:
            logger.error(f"Failed to generate Notes: {e}")
        return None

    def generate_slides(self, core: KnowledgeCore) -> Optional[SlidesModel]:
        """Generates a Lecture Slide Deck structure."""
        if not self.model: return None
        core_json = core.model_dump_json(indent=2)
        prompt = """
        You are an expert Content Designer.
        **Task**: Generate a SlidesModel.
        **Requirements**:
        - Create 10-12 slides.
        - **Structure**:
            - "title": "Presentation Title"
            - "audience_level": "Beginner/Intermediate"
            - "slides": List of objects:
                - "heading": "Slide Headline"
                - "main_idea": "One sentence summary"
                - "bullet_points": ["Point 1", "Point 2", "Point 3"]
                - "visual_cue": "Description of image/chart"
                - "speaker_notes": "Script for speaker"
        - **Math Formatting**: For Slides, DO NOT use LaTeX. Use Unicode characters for math where possible (e.g., use "∫" instead of "\\int", "∑" instead of "\\sum", "x²" instead of "x^2"). This is because the output target (PPTX) does not support LaTeX rendering.
        - **CRITICAL JSON SYNTAX**: You MUST double-escape backslashes in JSON strings if any remain.
        - Return strictly valid JSON.
        """
        try:
            logger.info("Generating Slides...")
            response = self.model.generate_content([prompt, core_json], generation_config=genai.GenerationConfig(response_mime_type="application/json"))
            if response.text:
                data = json.loads(response.text)
                if "slides" not in data and isinstance(data, list):
                    data = {"title": f"Slides: {core.title}", "slides": data, "audience_level": "Intermediate"}
                if "title" not in data: data["title"] = f"Slides: {core.title}"
                if "audience_level" not in data: data["audience_level"] = "General"
                return SlidesModel(**data)
        except Exception as e:
            logger.error(f"Failed to generate Slides: {e}")
        return None
