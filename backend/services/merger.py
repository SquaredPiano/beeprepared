"""Combines several knowledge cores into one context for generation."""

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
    """A single source compressed to a fixed budget."""

    source_title: str
    key_concepts: List[str]
    key_facts: List[str]
    summary: str


class CombinedContext(BaseModel):
    """What several sources say, taken together."""

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
    Compresses each source, then synthesises the summaries.

    Concatenating full sources does not scale: the combined text overruns the
    context window and the model attends mostly to whichever came first. Beyond
    a few sources the synthesis runs pairwise up a tree, so the prompt stays a
    bounded size however many sources are wired in.
    """

    def __init__(self, provider: Optional[LLMProvider] = None) -> None:
        self._provider = provider or get_provider()

    async def merge(self, cores: List[KnowledgeCore]) -> CombinedContext:
        """
        Reduce many knowledge cores to one context.

        `summarise` absorbs its own failures, so the only thing `gather` can
        hand back here is a cancelled child. Falling through to a structural
        summary would turn that teardown into a plausible-looking result, so it
        is re-raised instead. Cancelling the whole `merge` already propagates on
        its own; this covers a child cancelled by itself, which is what a
        per-call timeout inside `summarise` would produce.
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
        """Compress one core to a bounded summary."""
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
        """Combine summaries into one context, labelling any contradictions."""
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
