"""
CoreMerger: Hierarchical summarization and merge for multi-parent Knowledge Cores.

INVARIANTS:
- Each Core is summarized to ~500-800 tokens
- Summaries are merged with provenance preservation
- Conflicts are labeled, not resolved silently
- The output is a CombinedContext, not a KnowledgeCore
"""

import os
import logging
import json
from typing import List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai
from dotenv import load_dotenv

from backend.core.knowledge_core import KnowledgeCore

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()


class CoreSummary(BaseModel):
    """A compressed representation of a single Knowledge Core."""
    source_title: str = Field(description="Title of the original source")
    key_concepts: List[str] = Field(description="Top 5-7 most important concepts")
    key_facts: List[str] = Field(description="Top 5-7 critical facts")
    summary: str = Field(description="2-3 sentence high-level summary")
    token_estimate: int = Field(default=0, description="Estimated token count of this summary")


class CombinedContext(BaseModel):
    """
    The merged context from multiple Knowledge Cores.
    This is what gets passed to artifact generators.
    """
    source_count: int = Field(description="Number of sources merged")
    source_titles: List[str] = Field(description="Titles of all merged sources")
    unified_summary: str = Field(description="Synthesized summary across all sources")
    all_concepts: List[str] = Field(description="Deduplicated list of key concepts")
    all_facts: List[str] = Field(description="Deduplicated list of key facts")
    conflict_notes: Optional[str] = Field(default=None, description="Any noted conflicts between sources")


class CoreMerger:
    """
    Service for hierarchical summarization and merge of Knowledge Cores.
    
    Strategy:
    - 1 Core: Pass through (no summarization needed)
    - 2-3 Cores: Summarize each, then merge
    - 4+ Cores: Hierarchical (pairs → synth → meta-merge)
    """
    
    def __init__(self, model_name: str = 'gemini-2.0-flash'):
        self._setup_gemini(model_name)
    
    def _setup_gemini(self, model_name: str):
        api_key = os.getenv("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel(model_name)
                logger.info(f"[CoreMerger] Initialized with model: {model_name}")
            except Exception as e:
                logger.error(f"[CoreMerger] Failed to initialize Gemini: {e}")
                self.model = None
        else:
            logger.warning("[CoreMerger] GEMINI_API_KEY not found.")
            self.model = None
    
    def summarize_core(self, core: KnowledgeCore) -> CoreSummary:
        """
        Compress a Knowledge Core into a bounded summary (~500 tokens).
        If LLM fails, falls back to naive extraction.
        """
        if not self.model:
            return self._fallback_summarize(core)
        
        prompt = """
You are a Knowledge Compressor. Your task is to create a concise summary of the provided Knowledge Core.

**Requirements**:
1. **key_concepts**: Extract the 5-7 MOST important concepts (just the names/terms).
2. **key_facts**: Extract the 5-7 MOST critical facts (one sentence each).
3. **summary**: Write a 2-3 sentence high-level summary of what this material covers.

**Rules**:
- Be ruthlessly concise. Every word must earn its place.
- Preserve domain-specific terminology.
- Do not invent information. Only extract from the source.

**Output**: Return strictly valid JSON matching this schema:
{
  "source_title": "string",
  "key_concepts": ["string", ...],
  "key_facts": ["string", ...],
  "summary": "string"
}
"""
        
        try:
            core_json = core.model_dump_json(indent=2)
            response = self.model.generate_content(
                [prompt, core_json],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            
            if response.text:
                data = json.loads(response.text)
                data["source_title"] = core.title
                # Estimate tokens (rough: 1 token ≈ 4 chars)
                data["token_estimate"] = len(response.text) // 4
                return CoreSummary(**data)
            
        except Exception as e:
            logger.error(f"[CoreMerger] Summarization failed: {e}")
        
        return self._fallback_summarize(core)
    
    def _fallback_summarize(self, core: KnowledgeCore) -> CoreSummary:
        """Naive extraction if LLM fails."""
        return CoreSummary(
            source_title=core.title,
            key_concepts=[c.name for c in core.concepts[:7]],
            key_facts=[f.fact for f in core.key_facts[:7]],
            summary=core.summary[:500] if core.summary else "Summary unavailable.",
            token_estimate=200
        )
    
    def merge_summaries(self, summaries: List[CoreSummary]) -> CombinedContext:
        """
        Merge multiple CoreSummaries into a unified CombinedContext.
        Preserves provenance and labels conflicts.
        """
        if len(summaries) == 0:
            raise ValueError("Cannot merge zero summaries")
        
        if len(summaries) == 1:
            s = summaries[0]
            return CombinedContext(
                source_count=1,
                source_titles=[s.source_title],
                unified_summary=s.summary,
                all_concepts=s.key_concepts,
                all_facts=s.key_facts,
                conflict_notes=None
            )
        
        if not self.model:
            return self._fallback_merge(summaries)
        
        # Build input for LLM
        summaries_text = "\n\n".join([
            f"### Source: {s.source_title}\n**Concepts**: {', '.join(s.key_concepts)}\n**Facts**: {'; '.join(s.key_facts)}\n**Summary**: {s.summary}"
            for s in summaries
        ])
        
        prompt = f"""
You are merging knowledge from {len(summaries)} different sources.

**Your Task**:
1. Create a unified summary that synthesizes all sources (2-3 sentences).
2. Combine all concepts (deduplicate if same concept appears in multiple sources).
3. Combine all facts (deduplicate, but preserve unique information).
4. If sources contradict each other, note the conflict explicitly.

**Rules**:
- Each source is authoritative within its own scope.
- Do not invent new information.
- If facts conflict, label them: "Source A says X; Source B says Y."

**Sources**:
{summaries_text}

**Output**: Return strictly valid JSON:
{{
  "unified_summary": "string",
  "all_concepts": ["string", ...],
  "all_facts": ["string", ...],
  "conflict_notes": "string or null"
}}
"""
        
        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )
            
            if response.text:
                data = json.loads(response.text)
                return CombinedContext(
                    source_count=len(summaries),
                    source_titles=[s.source_title for s in summaries],
                    unified_summary=data.get("unified_summary", ""),
                    all_concepts=data.get("all_concepts", []),
                    all_facts=data.get("all_facts", []),
                    conflict_notes=data.get("conflict_notes")
                )
        
        except Exception as e:
            logger.error(f"[CoreMerger] Merge failed: {e}")
        
        return self._fallback_merge(summaries)
    
    def _fallback_merge(self, summaries: List[CoreSummary]) -> CombinedContext:
        """Naive merge if LLM fails."""
        all_concepts = []
        all_facts = []
        
        for s in summaries:
            all_concepts.extend(s.key_concepts)
            all_facts.extend(s.key_facts)
        
        # Deduplicate
        all_concepts = list(dict.fromkeys(all_concepts))
        all_facts = list(dict.fromkeys(all_facts))
        
        combined_summary = " ".join([s.summary for s in summaries])
        
        return CombinedContext(
            source_count=len(summaries),
            source_titles=[s.source_title for s in summaries],
            unified_summary=combined_summary[:500],
            all_concepts=all_concepts[:15],
            all_facts=all_facts[:15],
            conflict_notes=None
        )
    
    def merge_cores(self, cores: List[KnowledgeCore]) -> CombinedContext:
        """
        Main entry point: Takes N Knowledge Cores and returns a CombinedContext.
        
        Strategy:
        - 1 Core: Summarize directly
        - 2-3 Cores: Summarize each, then merge
        - 4+ Cores: Hierarchical (pairs → merge → final merge)
        """
        if len(cores) == 0:
            raise ValueError("Cannot merge zero cores")
        
        if len(cores) == 1:
            summary = self.summarize_core(cores[0])
            return self.merge_summaries([summary])
        
        # Summarize all cores
        logger.info(f"[CoreMerger] Summarizing {len(cores)} Knowledge Cores...")
        summaries = [self.summarize_core(c) for c in cores]
        
        if len(cores) <= 3:
            # Direct merge
            logger.info(f"[CoreMerger] Direct merge of {len(summaries)} summaries")
            return self.merge_summaries(summaries)
        
        # Hierarchical merge for 4+ cores
        logger.info(f"[CoreMerger] Hierarchical merge for {len(cores)} cores")
        
        # Pair-wise merge first
        intermediate_contexts = []
        for i in range(0, len(summaries), 2):
            pair = summaries[i:i+2]
            intermediate = self.merge_summaries(pair)
            intermediate_contexts.append(intermediate)
        
        # Convert intermediate contexts back to summary-like format for final merge
        final_summaries = [
            CoreSummary(
                source_title=f"Merged: {', '.join(ctx.source_titles)}",
                key_concepts=ctx.all_concepts[:7],
                key_facts=ctx.all_facts[:7],
                summary=ctx.unified_summary,
                token_estimate=300
            )
            for ctx in intermediate_contexts
        ]
        
        return self.merge_summaries(final_summaries)
