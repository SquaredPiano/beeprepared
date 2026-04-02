import asyncio
import logging
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from backend.core.services.llm_factory import LLMFactory
from backend.env import load_environment

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_environment()

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

EXTRACTION_PROMPT = """
You are an expert knowledge engineer. Extract a definitive "source of truth"
from the provided material.

Extract:
1. **Concepts** - the core ideas and abstractions discussed.
2. **Hierarchy** - a nested outline reflecting the logical flow of the material.
3. **Notes** - comprehensive detailed notes, grouped by topic.
4. **Definitions** - terminology, with the context it was used in.
5. **Examples** - concrete examples, metaphors and stories used to illustrate points.
6. **Key facts** - atomic, objective facts stated in the material.

Be exhaustive. Capture every meaningful idea; prefer detail in the notes over
brevity. Write plain text only - no LaTeX, no Markdown syntax.
"""

# Above this many characters a single request starts losing detail at the tail
# of the document, so the extraction is mapped over chunks and reduced instead.
SINGLE_PASS_CHAR_LIMIT = 24_000
CHUNK_CHARS = 12_000


class KnowledgeCoreService:
    """Extracts the structured ``KnowledgeCore`` that the whole graph derives from."""

    def __init__(self, llm=None):
        self.llm = llm or LLMFactory.get_provider()

    async def generate_knowledge_core(self, clean_text: str) -> KnowledgeCore:
        """
        Build a ``KnowledgeCore`` from cleaned source text.

        Short documents go through in one request. Longer ones are chunked, each
        chunk extracted concurrently, and the partial cores merged - a lecture
        transcript can easily exceed what one request can attend to properly,
        and the tail of the document is exactly where detail was being lost.
        """
        if not clean_text or not clean_text.strip():
            raise ValueError("Input text is empty")

        if len(clean_text) <= SINGLE_PASS_CHAR_LIMIT:
            logger.info("Generating Knowledge Core in a single pass (%d chars)", len(clean_text))
            return await self._extract(clean_text)

        chunks = [clean_text[i:i + CHUNK_CHARS] for i in range(0, len(clean_text), CHUNK_CHARS)]
        logger.info("Generating Knowledge Core map/reduce over %d chunks", len(chunks))

        results = await asyncio.gather(
            *(self._extract(chunk) for chunk in chunks), return_exceptions=True
        )
        partials = [r for r in results if isinstance(r, KnowledgeCore)]
        if not partials:
            failures = "; ".join(str(r) for r in results if isinstance(r, Exception))
            raise RuntimeError(f"Knowledge Core extraction failed for every chunk: {failures}")

        if len(partials) < len(chunks):
            logger.warning("%d/%d chunks failed extraction; merging what succeeded",
                           len(chunks) - len(partials), len(chunks))
        return self._merge(partials)

    async def _extract(self, text: str) -> KnowledgeCore:
        result = await self.llm.generate_content_async(
            prompt=EXTRACTION_PROMPT,
            context=text,
            schema=KnowledgeCore,
        )
        if isinstance(result, KnowledgeCore):
            return result
        if isinstance(result, dict):
            return KnowledgeCore(**result)
        raise RuntimeError(f"LLM returned {type(result).__name__}, expected KnowledgeCore")

    @staticmethod
    def _merge(cores: List[KnowledgeCore]) -> KnowledgeCore:
        """
        Reduce partial cores into one, de-duplicating on the natural key of each
        collection so a concept discussed in three chunks appears once.
        """
        if len(cores) == 1:
            return cores[0]

        def dedupe(items: List[Any], key) -> List[Any]:
            seen: set = set()
            out: List[Any] = []
            for item in items:
                identity = str(key(item)).strip().lower()
                if identity and identity not in seen:
                    seen.add(identity)
                    out.append(item)
            return out

        return KnowledgeCore(
            title=cores[0].title,
            summary=" ".join(core.summary for core in cores if core.summary)[:4000],
            concepts=dedupe([c for core in cores for c in core.concepts], lambda c: c.name),
            section_hierarchy=dedupe(
                [s for core in cores for s in core.section_hierarchy], lambda s: s.title
            ),
            notes=dedupe([n for core in cores for n in core.notes], lambda n: n.heading),
            definitions=dedupe([d for core in cores for d in core.definitions], lambda d: d.term),
            examples=dedupe([e for core in cores for e in core.examples], lambda e: e.description),
            key_facts=dedupe([k for core in cores for k in core.key_facts], lambda k: k.fact),
        )

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
