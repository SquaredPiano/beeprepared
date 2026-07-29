"""Boils several knowledge cores down into one context to generate from."""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.llm.base import LLMProvider
from backend.llm.factory import get_provider
from backend.pipeline.knowledge import KnowledgeCore

logger = logging.getLogger(__name__)

CONCEPTS_PER_SOURCE = 7
FACTS_PER_SOURCE = 7
DIRECT_MERGE_LIMIT = 3

SUMMARISE_PROMPT = f"""
You are compressing one source into a fixed-size summary for cross-source merging.

Produce at most {CONCEPTS_PER_SOURCE} key concepts, at most {FACTS_PER_SOURCE}
key facts, and a two or three sentence summary.

Rules:
1. Keep what a learner would be tested on. Drop asides and repetition.
2. Concepts are noun phrases; facts are complete statements.
3. Preserve the source's own terminology, which matters when merging.
4. Invent nothing.
"""

SYNTHESISE_PROMPT = """
You are synthesising several sources into one study context.

Rules:
1. Merge concepts that are the same idea under different names, keeping both
   namings when the wording differs meaningfully.
2. If two sources disagree on a fact, keep BOTH and record the disagreement in
   conflict_notes, naming the sources. Never silently pick a winner.
3. The unified summary must reflect every source, not just the longest one.
4. Each source is authoritative within its own scope. Invent nothing.
5. Plain text only: no Markdown, no LaTeX.
"""


class CoreSummary(BaseModel):
    """One source squeezed down to a fixed budget."""

    source_title: str
    key_concepts: List[str]
    key_facts: List[str]
    summary: str


class CombinedContext(BaseModel):
    """What all the sources say, once you put them together."""

    source_count: int
    source_titles: List[str]
    unified_summary: str
    all_concepts: List[str]
    all_facts: List[str]
    conflict_notes: Optional[str] = Field(
        default=None, description="Contradictions between sources, labelled not resolved"
    )


class CoreMerger:
    """
    Compresses each source on its own, then merges the summaries together.

    It's a map and then a reduce. Pasting the full sources end to end doesn't
    scale. The combined text runs past the context window, and what does fit gets
    read mostly for whichever source happened to come first. Past three sources
    the merge goes pairwise up a tree, so a node fed by twenty lectures sends a
    prompt about the same size as a node fed by three.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    async def merge(self, cores: List[KnowledgeCore]) -> CombinedContext:
        """
        Reduce any number of knowledge cores to a single context.

        `summarise` swallows its own failures, so the only bad thing `gather` can
        hand back here is a child that got cancelled. If we fell through to a
        structural summary on one of those, we'd turn a teardown into a result
        that looks perfectly plausible, so we re-raise it. Cancelling the whole
        `merge` already propagates on its own. What this covers is a child that
        was cancelled by itself, which is what a per-call timeout inside
        `summarise` would look like.
        """
        if not cores:
            raise ValueError("merge needs at least one knowledge core")

        results = await asyncio.gather(
            *(self.summarise(core) for core in cores), return_exceptions=True
        )
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result

        summaries = [
            result if isinstance(result, CoreSummary) else self._structural_summary(core)
            for core, result in zip(cores, results)
        ]

        level = summaries
        while len(level) > DIRECT_MERGE_LIMIT:
            pairs = [level[index : index + 2] for index in range(0, len(level), 2)]
            logger.info("Reducing %d summaries into %d", len(level), len(pairs))
            contexts = await asyncio.gather(*(self.synthesise(pair) for pair in pairs))
            level = [self._as_summary(context) for context in contexts]

        return await self.synthesise(level)

    async def summarise(self, core: KnowledgeCore) -> CoreSummary:
        """
        Compress one core down to a summary of bounded size.

        If the model call falls over we build the summary from the core's own
        fields, because a blunt summary still beats dropping that source out of
        the merge altogether.
        """
        try:
            summary = await self._provider.complete_as(
                SUMMARISE_PROMPT, CoreSummary, context=core.model_dump_json()
            )
            summary.source_title = core.title or summary.source_title
            return summary
        except Exception as error:
            logger.warning("Summarising '%s' failed (%s); using its own fields", core.title, error)
            return self._structural_summary(core)

    async def synthesise(self, summaries: List[CoreSummary]) -> CombinedContext:
        """Merge summaries into one context, and label the places they disagree."""
        if not summaries:
            raise ValueError("synthesise needs at least one summary")

        if len(summaries) == 1:
            only = summaries[0]
            return CombinedContext(
                source_count=1,
                source_titles=[only.source_title],
                unified_summary=only.summary,
                all_concepts=only.key_concepts,
                all_facts=only.key_facts,
            )

        try:
            merged = await self._provider.complete_as(
                SYNTHESISE_PROMPT, CombinedContext, context=self._render(summaries)
            )
            merged.source_count = len(summaries)
            merged.source_titles = [summary.source_title for summary in summaries]
            return merged
        except Exception as error:
            logger.warning("Synthesis failed (%s); falling back to a structural merge", error)
            return self._structural_merge(summaries)

    @staticmethod
    def _render(summaries: List[CoreSummary]) -> str:
        return "\n\n".join(
            f"### Source {index + 1}: {summary.source_title}\n"
            f"Summary: {summary.summary}\n"
            f"Concepts: {', '.join(summary.key_concepts)}\n"
            "Facts:\n" + "\n".join(f"- {fact}" for fact in summary.key_facts)
            for index, summary in enumerate(summaries)
        )

    @staticmethod
    def _structural_summary(core: KnowledgeCore) -> CoreSummary:
        ranked = sorted(core.concepts, key=lambda concept: -(concept.importance_score or 0))
        return CoreSummary(
            source_title=core.title,
            key_concepts=[concept.name for concept in ranked[:CONCEPTS_PER_SOURCE]],
            key_facts=[fact.fact for fact in core.key_facts[:FACTS_PER_SOURCE]],
            summary=(core.summary or "Summary unavailable.")[:800],
        )

    @staticmethod
    def _structural_merge(summaries: List[CoreSummary]) -> CombinedContext:
        def union(values: List[str]) -> List[str]:
            seen: set = set()
            result = []
            for value in values:
                identity = value.strip().lower()
                if identity and identity not in seen:
                    seen.add(identity)
                    result.append(value.strip())
            return result

        return CombinedContext(
            source_count=len(summaries),
            source_titles=[summary.source_title for summary in summaries],
            unified_summary=" ".join(
                f"From {summary.source_title}: {summary.summary}" for summary in summaries
            )[:4000],
            all_concepts=union([c for s in summaries for c in s.key_concepts]),
            all_facts=union([f for s in summaries for f in s.key_facts]),
        )

    @staticmethod
    def _as_summary(context: CombinedContext) -> CoreSummary:
        return CoreSummary(
            source_title=f"Merged: {', '.join(context.source_titles)}",
            key_concepts=context.all_concepts[:CONCEPTS_PER_SOURCE],
            key_facts=context.all_facts[:FACTS_PER_SOURCE],
            summary=context.unified_summary,
        )
