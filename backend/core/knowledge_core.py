import os
import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from google import genai
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# --- Pydantic Data Models (Schema) ---

class Concept(BaseModel):
    name: str = Field(description="Name of the core concept")
    description: str = Field(description="Detailed explanation of the concept")
    importance_score: int = Field(description="Relevance score from 1-10")

class Definition(BaseModel):
    term: str = Field(description="The technical term or jargon")
    definition: str = Field(description="Clear, concise definition")
    context: str = Field(description="Context in which this term was used")

class Example(BaseModel):
    description: str = Field(description="Description of the example or metaphor used")
    relevance: str = Field(description="Why this example is relevant to the topic")

class KeyFact(BaseModel):
    fact: str = Field(description="An atomic, indisputable fact stated in the content")
    category: str = Field(description="Category of the fact (e.g., 'Historical', 'Technical', 'Statistical')")

class Subsection(BaseModel):
    title: str = Field(description="Title of the subsection")
    summary: str = Field(description="Brief summary of this subsection")

class Section(BaseModel):
    title: str = Field(description="Title of the main section")
    summary: str = Field(description="Brief summary of this section")
    subsections: List[Subsection] = Field(default_factory=list, description="List of subsections")

class NoteContent(BaseModel):
    heading: str = Field(description="Heading for this block of notes")
    bullets: List[str] = Field(description="List of detailed note bullet points")

class KnowledgeCore(BaseModel):
    title: str = Field(description="Overall title of the content")
    summary: str = Field(description="High-level executive summary")
    concepts: List[Concept] = Field(description="Key concepts extracted")
    section_hierarchy: List[Section] = Field(description="Hierarchical outline of the content (Sections and Subsections)")
    notes: List[NoteContent] = Field(description="Detailed notes grouped by logic/heading")
    definitions: List[Definition] = Field(description="Dictionary of terms defined")
    examples: List[Example] = Field(description="List of illustrative examples")
    key_facts: List[KeyFact] = Field(description="List of key atomic facts")

# --- Service Implementation ---

class KnowledgeCoreService:
    def __init__(self):
        self._setup_gemini()

    def _setup_gemini(self):
        """Initialize Gemini client."""
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
                self.model_name = 'gemini-2.0-flash'
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.client = None
        else:
            logger.warning("GEMINI_API_KEY not found. Knowledge Core generation will fail.")
            self.client = None


    def generate_knowledge_core(self, clean_text: str) -> Optional[KnowledgeCore]:
        """
        Generates the Knowledge Core JSON structure from cleaned text.
        """
        if not self.client:
            logger.error("Gemini client is not initialized.")
            return None

        if not clean_text:
            logger.warning("Input text is empty.")
            return None

        logger.info("Generating Knowledge Core (this may take a moment)...")

        prompt = """
        You are an expert Knowledge Engineer. Your goal is to extract a definitive "Source of Truth" from the provided transcript.
        
        Analyze the text deeply and extract the following structured data:
        1.  **Concepts**: The core ideas and abstract concepts discussed.
        2.  **Hierarchy**: A nested outline of the content (Sections/Subsections).
        3.  **Notes**: Comprehensive, detailed notes organized by topic.
        4.  **Definitions**: Specific terminology and their definitions.
        5.  **Examples**: Concrete examples, metaphors, or stories used to illustrate points.
        6.  **Key Facts**: Atomic, objective facts mentioned.

        Be exhaustive. Capture ALL meaningful information.
        Do not summarize wildly; prefer detail in the Notes section.
        Ensure the 'section_hierarchy' reflects the logical flow of the lecture/text.
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[prompt, clean_text],
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': KnowledgeCore
                }
            )
            
            # The SDK returns a parsed object if response_schema is a Pydantic model
            if response.parsed:
                return response.parsed
            else:
                logger.error("Failed to parse structured output.")
                return None

        except Exception as e:
            logger.error(f"Knowledge Core generation failed: {e}")
            return None

if __name__ == "__main__":
    # Test Block
    import json
    
    # Read the cleaned output file if it exists, otherwise use dummy text
    input_file = "cleaned_output.txt"
    if os.path.exists(input_file):
        with open(input_file, "r") as f:
            text_input = f.read()
    else:
        text_input = "This looks like a transcript about Software Engineering. The key concept is Modular Design. Ideally, files should be short."

    service = KnowledgeCoreService()
    core = service.generate_knowledge_core(text_input)
    
    if core:
        print("\n--- Knowledge Core Generated Successfully ---\n")
        print(f"Title: {core.title}")
        print(f"Concepts Found: {len(core.concepts)}")
        print(f"Main Sections: {len(core.section_hierarchy)}")
        
        # Save to JSON for inspection
        output_json = "knowledge_core.json"
        with open(output_json, "w") as f:
            f.write(core.model_dump_json(indent=2))
        print(f"\nFull Knowledge Core saved to {output_json}")
    else:
        print("Failed to generate Knowledge Core.")
