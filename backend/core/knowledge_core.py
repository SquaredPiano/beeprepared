import os
import logging
from typing import List, Optional, Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from backend.core.services.llm_factory import LLMFactory

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

# --- Pydantic Data Models (Schema) ---
# (Keeping models same as before)
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

class KnowledgeCoreService:
    def __init__(self):
        self._setup_llm()

    def _setup_llm(self):
        """Initialize LLM Provider via Factory."""
        try:
            self.llm = LLMFactory.get_provider()
        except Exception as e:
            logger.error(f"Failed to initialize LLM Provider: {e}")
            self.llm = None


    async def generate_knowledge_core(self, clean_text: str) -> KnowledgeCore:
        """
        Generates the Knowledge Core JSON structure from cleaned text using the abstract LLM provider.
        Async execution.
        """
        if not self.llm:
            raise RuntimeError("LLM Provider is not initialized")

        if not clean_text:
            raise ValueError("Input text is empty")

        logger.info("Generating Knowledge Core via LLM Provider (Async Pro Model)...")

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
            # Request High Quality Model (Pro)
            # Fallback handling: provider logs warning if model not found and uses default? 
            # Or implementation throws? Vertex usually supports it.
            model_to_use = "gemini-2.0-flash-exp" 
            
            # Check if using Gemini provider (names might differ slightly or just use same)
            # Currently VertexLLM and GeminiLLM both accept model_name overrides.
            
            response_model = await self.llm.generate_content_async(
                prompt=prompt,
                context=clean_text,
                schema=KnowledgeCore,
                model_name=model_to_use
            )
            
            if isinstance(response_model, KnowledgeCore):
                return response_model
            else:
                logger.error(f"Provider returned unexpected type: {type(response_model)}")
                raise RuntimeError("LLM Provider returned invalid type (expected KnowledgeCore object)")

        except Exception as e:
            logger.error(f"Knowledge Core generation failed: {e}")
            raise e

if __name__ == "__main__":
    import asyncio
    
    async def test():
        service = KnowledgeCoreService()
        text = "This is a test transcript."
        try:
            res = await service.generate_knowledge_core(text)
            print(res.title)
        except Exception as e:
            print(f"Error: {e}")

    asyncio.run(test())
