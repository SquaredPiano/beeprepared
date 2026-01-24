import os
import json
import logging
from backend.models.artifacts import FinalExamModel
from backend.services.generators import ArtifactGenerator
from backend.services.pdf_renderer import PDFRenderer
from backend.knowledge_core import KnowledgeCore

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    # 1. Load Knowledge Core
    core_path = "backend/knowledge_core.json"
    if not os.path.exists(core_path):
        logger.error(f"Knowledge Core file not found at {core_path}. Run knowledge_core.py first.")
        return

    try:
        with open(core_path, "r") as f:
            data = json.load(f)
            core = KnowledgeCore(**data)
            logger.info(f"Loaded Knowledge Core: '{core.title}'")
    except Exception as e:
        logger.error(f"Failed to load Knowledge Core: {e}")
        return

    generator = ArtifactGenerator(model_name='gemini-flash-latest')
    renderer = PDFRenderer(output_dir="output")
    
    # # --- 2. Final Exam (V2) ---
    # logger.info("--- Testing Final Exam Generation ---")
    # exam = generator.generate_exam(core)
    # if exam:
    #     with open("final_exam.json", "w") as f:
    #         f.write(exam.model_dump_json(indent=2))
    #     logger.info("Saved final_exam.json")
    #     renderer.render_exam(exam, filename="final_exam")
    
    # --- 3. Quiz ---
    logger.info("--- Testing Quiz Generation ---")
    quiz = generator.generate_quiz(core)
    if quiz:
        with open("output/quiz.json", "w") as f:
            f.write(quiz.model_dump_json(indent=2))
        logger.info("Saved output/quiz.json")
        
        # Test Transform
        from backend.services.transforms import quiz_to_flashcards
        fc_from_quiz = quiz_to_flashcards(quiz)
        with open("output/flashcards_from_quiz.json", "w") as f:
            f.write(fc_from_quiz.model_dump_json(indent=2))
            
    # --- 4. Flashcards ---
    logger.info("--- Testing Flashcards Generation ---")
    cards = generator.generate_flashcards(core)
    if cards:
        with open("output/flashcards.json", "w") as f:
            f.write(cards.model_dump_json(indent=2))
        logger.info("Saved output/flashcards.json")
        
    # --- 5. Notes ---
    logger.info("--- Testing Notes Generation ---")
    notes = generator.generate_notes(core)
    if notes:
        with open("output/notes.json", "w") as f:
            f.write(notes.model_dump_json(indent=2))
        # Render Markdown File
        with open("output/study_notes.md", "w") as f:
            f.write(f"# {notes.title}\n\n")
            # Iterate sections
            for section in notes.sections:
                f.write(f"## {section.heading}\n")
                f.write(section.content_block + "\n\n")
                if section.key_points:
                    f.write("### Key Points\n")
                    for kp in section.key_points:
                        f.write(f"- {kp}\n")
                f.write("\n")
                
                if section.callouts:
                    for callout in section.callouts:
                         f.write(f"> [!NOTE]\n> {callout}\n\n")

            # Global Glossary (Accumulate from sections or if strict model had it)
            # Schema 'sections' has key_terms list.
            # We can aggregate them at the end.
            f.write("## Glossary\n")
            for section in notes.sections:
                for term in section.key_terms:
                    f.write(f"- **{term}**\n")
        logger.info("Saved output/study_notes.md")
        
    # --- 6. Slides ---
    logger.info("--- Testing Slides Generation ---")
    slides = generator.generate_slides(core)
    if slides:
        with open("output/slides.json", "w") as f:
            f.write(slides.model_dump_json(indent=2))
        logger.info("Saved output/slides.json")

    logger.info("All artifact tests complete.")

if __name__ == "__main__":
    main()
