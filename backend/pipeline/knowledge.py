"""Distils cleaned source text into the knowledge core everything derives from."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, List, Optional

from pydantic import BaseModel, Field

from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider

logger = logging.getLogger(__name__)

SINGLE_PASS_LIMIT = 24_000
CHUNK_SIZE = 12_000

EXTRACTION_PROMPT = """
You are an expert knowledge engineer. Extract a definitive source of truth from
the provided material.

Extract:
1. Concepts - the core ideas and abstractions discussed.
2. Hierarchy - a nested outline following the logical flow of the material.
3. Notes - comprehensive detailed notes, grouped by topic.
4. Definitions - terminology, with the context it was used in.
5. Examples - concrete examples, metaphors and stories used to illustrate points.
6. Key facts - atomic, objective statements made in the material.

Be exhaustive; prefer detail in the notes over brevity. Write plain text only,
with no LaTeX and no Markdown syntax.
"""


class Concept(BaseModel):
    name: str
    description: str
    importance_score: int = Field(description="Relevance from 1 to 10")


class Definition(BaseModel):
    term: str
    definition: str
    context: str = Field(description="How the term was used here")


class Example(BaseModel):
    description: str
    relevance: str


class KeyFact(BaseModel):
    fact: str
    category: str


class Subsection(BaseModel):
    title: str
    summary: str


class Section(BaseModel):
    title: str
    summary: str
    subsections: List[Subsection] = Field(default_factory=list)


class NoteBlock(BaseModel):
    heading: str
    bullets: List[str]


class KnowledgeCore(BaseModel):
    """
    The structured understanding of one body of source material.

    Every generated artifact reads from this rather than from the raw text,
    which is what keeps a project's quiz, notes and exam consistent.
    """

    title: str
    summary: str
    concepts: List[Concept]
    section_hierarchy: List[Section]
    notes: List[NoteBlock]
    definitions: List[Definition]
    examples: List[Example]
    key_facts: List[KeyFact]


class KnowledgeExtractor:
    """
    Builds a `KnowledgeCore` from cleaned text.

    Long documents are split, extracted concurrently and merged, because a
    single request over a whole transcript loses detail towards the end.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    async def extract(self, text: str) -> KnowledgeCore:
        """Distil `text` into a knowledge core."""
        if not text or not text.strip():
            raise ValueError("Cannot build a knowledge core from empty text")

        if len(text) <= SINGLE_PASS_LIMIT:
            logger.info("Extracting knowledge core in one pass (%d chars)", len(text))
            return await self._extract_one(text)

        chunks = [text[index : index + CHUNK_SIZE] for index in range(0, len(text), CHUNK_SIZE)]
        logger.info("Extracting knowledge core across %d chunks", len(chunks))

        results = await asyncio.gather(
            *(self._extract_one(chunk) for chunk in chunks),
            return_exceptions=True,
        )
        cores = [result for result in results if isinstance(result, KnowledgeCore)]

        if not cores:
            reasons = "; ".join(
                f"{type(result).__name__}: {result}"
                for result in results
                if isinstance(result, BaseException)
            )
            raise RuntimeError(f"Every chunk failed extraction: {reasons}")

        if len(cores) < len(chunks):
            logger.warning("%d/%d chunks failed; merging the rest", len(chunks) - len(cores), len(chunks))

        return self.merge(cores)

    async def _extract_one(self, text: str) -> KnowledgeCore:
        return await self._provider.complete_as(EXTRACTION_PROMPT, KnowledgeCore, context=text)

    @staticmethod
    def merge(cores: List[KnowledgeCore]) -> KnowledgeCore:
        """Combine partial cores, de-duplicating each collection on its natural key."""
        if len(cores) == 1:
            return cores[0]

        def unique(items: List[Any], key: Callable[[Any], str]) -> List[Any]:
            seen: set = set()
            result = []
            for item in items:
                identity = str(key(item)).strip().lower()
                if identity and identity not in seen:
                    seen.add(identity)
                    result.append(item)
            return result

        def flatten(attribute: str) -> List[Any]:
            return [item for core in cores for item in getattr(core, attribute)]

        return KnowledgeCore(
            title=cores[0].title,
            summary=" ".join(core.summary for core in cores if core.summary)[:4000],
            concepts=unique(flatten("concepts"), lambda item: item.name),
            section_hierarchy=unique(flatten("section_hierarchy"), lambda item: item.title),
            notes=unique(flatten("notes"), lambda item: item.heading),
            definitions=unique(flatten("definitions"), lambda item: item.term),
            examples=unique(flatten("examples"), lambda item: item.description),
            key_facts=unique(flatten("key_facts"), lambda item: item.fact),
        )
