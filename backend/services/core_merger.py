"""
Multi-source context merging.

When a generator node has several inputs - three lecture recordings, or a slide
deck plus a textbook chapter - their Knowledge Cores have to become one context
before generation. Concatenating them does not scale: the combined document
overruns the context window and the model attends mostly to whichever source
happened to come first.

So this does a map/reduce instead:

1. **Map**: compress each core to a fixed-size summary. Runs concurrently, one
   request per source.
2. **Reduce**: synthesise the summaries into a single ``CombinedContext``,
   de-duplicating concepts and *labelling* contradictions between sources
   rather than silently picking a winner.
3. Past a handful of sources the reduce is done pairwise up a tree, so the
   prompt stays a bounded size no matter how many lectures are wired in.

The merger talks to ``LLMProvider``, so it works with whichever model is
configured, and it degrades to a deterministic structural merge if the model
call fails - a plainer merge beats a failed job.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.core.knowledge_core import KnowledgeCore
from backend.core.llm_interface import LLMProvider
from backend.core.services.llm_factory import LLMFactory

logger = logging.getLogger(__name__)

# Carried per source into the reduce step. Enough to preserve the shape of each
# source without letting one long document dominate the prompt.
PER_SOURCE_CONCEPTS = 7
PER_SOURCE_FACTS = 7

# Above this many sources, reduce pairwise up a tree instead of in one request.
DIRECT_MERGE_LIMIT = 3


class CoreSummary(BaseModel):
    """A compressed representation of a single Knowledge Core."""

    source_title: str = Field(description="Title of the original source")
    key_concepts: List[str] = Field(description="The 5-7 most important concepts")
    key_facts: List[str] = Field(description="The 5-7 most critical facts")
    summary: str = Field(description="Two or three sentence high-level summary")


class CombinedContext(BaseModel):
    """Merged context across sources. This is what generators consume."""

    source_count: int = Field(description="Number of sources merged")
    source_titles: List[str] = Field(description="Titles of all merged sources")
    unified_summary: str = Field(description="Synthesised summary across all sources")
    all_concepts: List[str] = Field(description="De-duplicated concepts")
    all_facts: List[str] = Field(description="De-duplicated facts")
    conflict_notes: Optional[str] = Field(
        default=None, description="Contradictions between sources, labelled rather than resolved"
    )


class CoreMerger:
    """Compresses and merges Knowledge Cores from multiple sources."""

    def __init__(self, llm: Optional[LLMProvider] = None):
        self.llm = llm or LLMFactory.get_provider()

    # -- map ----------------------------------------------------------------

    async def summarize_core(self, core: KnowledgeCore) -> CoreSummary:
        """Compress one core to a bounded summary."""
        prompt = f"""
You are compressing one source into a fixed-size summary for cross-source merging.

**Task**: Produce at most {PER_SOURCE_CONCEPTS} key concepts, at most
{PER_SOURCE_FACTS} key facts, and a two to three sentence summary.

**Rules**:
1. Keep what a learner would be tested on; drop asides and repetition.
2. Concepts are noun phrases; facts are complete statements.
3. Preserve the source's own terminology - it matters when merging.
4. Do not invent anything that is not in the source.
"""
        try:
            result = await self.llm.generate_content_async(
                prompt=prompt, context=core.model_dump_json(), schema=CoreSummary
            )
            summary = result if isinstance(result, CoreSummary) else CoreSummary(**result)
            summary.source_title = core.title or summary.source_title
            return summary
        except Exception as exc:
            logger.warning("Summarisation failed for '%s' (%s); using structural fallback", core.title, exc)
            return self._structural_summary(core)

    @staticmethod
    def _structural_summary(core: KnowledgeCore) -> CoreSummary:
        """Deterministic compression straight from the core's own fields."""
        ranked = sorted(core.concepts, key=lambda c: -(c.importance_score or 0))
        return CoreSummary(
            source_title=core.title,
            key_concepts=[c.name for c in ranked[:PER_SOURCE_CONCEPTS]],
            key_facts=[f.fact for f in core.key_facts[:PER_SOURCE_FACTS]],
            summary=(core.summary or "Summary unavailable.")[:800],
        )

    # -- reduce -------------------------------------------------------------

    async def merge_summaries(self, summaries: List[CoreSummary]) -> CombinedContext:
        """Synthesise summaries into one context, labelling any contradictions."""
        if not summaries:
            raise ValueError("Cannot merge zero summaries")

        if len(summaries) == 1:
            only = summaries[0]
            return CombinedContext(
                source_count=1,
                source_titles=[only.source_title],
                unified_summary=only.summary,
                all_concepts=only.key_concepts,
                all_facts=only.key_facts,
            )

        rendered = "\n\n".join(
            f"### Source {index + 1}: {summary.source_title}\n"
            f"Summary: {summary.summary}\n"
            f"Concepts: {', '.join(summary.key_concepts)}\n"
            "Facts:\n" + "\n".join(f"- {fact}" for fact in summary.key_facts)
            for index, summary in enumerate(summaries)
        )

        prompt = f"""
You are synthesising {len(summaries)} sources into one study context.

**Task**: Produce a unified summary, a de-duplicated concept list, a
de-duplicated fact list, and conflict notes.

**Rules**:
1. Merge concepts that are the same idea under different names; keep both
   namings in the concept string when the wording differs meaningfully.
2. If two sources disagree on a fact, keep BOTH and record the disagreement in
   "conflict_notes", naming the sources. Never silently pick a winner.
3. The unified summary must reflect every source, not just the longest one.
4. Each source is authoritative within its own scope. Invent nothing.
5. Plain text only - no Markdown, no LaTeX.
"""
        try:
            result = await self.llm.generate_content_async(
                prompt=prompt, context=rendered, schema=CombinedContext
            )
            merged = result if isinstance(result, CombinedContext) else CombinedContext(**result)
            # The model does not reliably echo bookkeeping fields back.
            merged.source_count = len(summaries)
            merged.source_titles = [s.source_title for s in summaries]
            return merged
        except Exception as exc:
            logger.warning("Cross-source synthesis failed (%s); using structural merge", exc)
            return self._structural_merge(summaries)

    @staticmethod
    def _structural_merge(summaries: List[CoreSummary]) -> CombinedContext:
        """Order-preserving de-duplicated union, used when the model is unavailable."""

        def union(values: List[str]) -> List[str]:
            seen: set = set()
            out: List[str] = []
            for value in values:
                identity = value.strip().lower()
                if identity and identity not in seen:
                    seen.add(identity)
                    out.append(value.strip())
            return out

        return CombinedContext(
            source_count=len(summaries),
            source_titles=[s.source_title for s in summaries],
            unified_summary=" ".join(
                f"From {s.source_title}: {s.summary}" for s in summaries
            )[:4000],
            all_concepts=union([c for s in summaries for c in s.key_concepts]),
            all_facts=union([f for s in summaries for f in s.key_facts]),
            conflict_notes=None,
        )

    @staticmethod
    def _as_summary(context: CombinedContext) -> CoreSummary:
        """Fold an intermediate context back into a summary for the next level up."""
        return CoreSummary(
            source_title=f"Merged: {', '.join(context.source_titles)}",
            key_concepts=context.all_concepts[:PER_SOURCE_CONCEPTS],
            key_facts=context.all_facts[:PER_SOURCE_FACTS],
            summary=context.unified_summary,
        )

    # -- entry point --------------------------------------------------------

    async def merge_cores(self, cores: List[KnowledgeCore]) -> CombinedContext:
        """Compress every core concurrently, then reduce them into one context."""
        if not cores:
            raise ValueError("merge_cores requires at least one Knowledge Core")

        results = await asyncio.gather(
            *(self.summarize_core(core) for core in cores), return_exceptions=True
        )
        summaries = [
            result if isinstance(result, CoreSummary) else self._structural_summary(core)
            for core, result in zip(cores, results)
        ]

        if len(summaries) <= DIRECT_MERGE_LIMIT:
            return await self.merge_summaries(summaries)

        # Reduce pairwise up a tree so the prompt never grows with source count.
        level = summaries
        while len(level) > DIRECT_MERGE_LIMIT:
            pairs = [level[i:i + 2] for i in range(0, len(level), 2)]
            logger.info("Hierarchical merge: reducing %d summaries into %d", len(level), len(pairs))
            contexts = await asyncio.gather(*(self.merge_summaries(pair) for pair in pairs))
            level = [self._as_summary(context) for context in contexts]

        return await self.merge_summaries(level)
