"""
Multi-Parent Merge Test Suite

Tests the hierarchical summarization and merge pipeline for DAG-based generation.

Run with: python -m pytest tests/test_multi_parent_merge.py -v
Or: python tests/test_multi_parent_merge.py
"""

import os
import sys
import asyncio
import logging

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from backend.core.knowledge_core import KnowledgeCore, Concept, KeyFact, Section
from backend.services.core_merger import CoreMerger, CoreSummary, CombinedContext

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Test Fixtures
# =============================================================================

def make_mock_core(title: str, concepts: list[str], facts: list[str]) -> KnowledgeCore:
    """Create a mock KnowledgeCore for testing."""
    return KnowledgeCore(
        title=title,
        summary=f"Summary of {title}",
        concepts=[Concept(name=c, description=f"Description of {c}", importance_score=7) for c in concepts],
        key_facts=[KeyFact(fact=f, category="Test") for f in facts],
        notes=[],
        section_hierarchy=[Section(title="Main", summary="Main section", subsections=[])],
        definitions=[],
        examples=[]
    )


BIOLOGY_CORE = make_mock_core(
    "Biology Lecture",
    ["Cell Division", "DNA Replication", "Mitosis"],
    ["Cells divide via mitosis", "DNA is double-stranded"]
)

CHEMISTRY_CORE = make_mock_core(
    "Chemistry Lecture",
    ["Atoms", "Molecules", "Chemical Bonds"],
    ["Atoms have electrons", "Covalent bonds share electrons"]
)

PHYSICS_CORE = make_mock_core(
    "Physics Lecture",
    ["Force", "Mass", "Acceleration"],
    ["F=ma", "Energy is conserved"]
)


# =============================================================================
# Unit Tests: CoreMerger
# =============================================================================

class TestCoreMerger:
    """Unit tests for the CoreMerger service."""
    
    def setup_method(self):
        self.merger = CoreMerger()
    
    def test_summarize_core_returns_bounded_summary(self):
        """Test that summarize_core returns a bounded CoreSummary."""
        summary = self.merger.summarize_core(BIOLOGY_CORE)
        
        assert isinstance(summary, CoreSummary)
        assert summary.source_title == "Biology Lecture"
        assert len(summary.key_concepts) <= 7  # Bounded
        assert len(summary.key_facts) <= 7     # Bounded
        assert len(summary.summary) > 0
        
        logger.info(f"✅ summarize_core: {summary.source_title} -> {len(summary.summary)} chars")
    
    def test_merge_single_core_passthrough(self):
        """Test that single core is passed through correctly."""
        result = self.merger.merge_cores([BIOLOGY_CORE])
        
        assert isinstance(result, CombinedContext)
        assert result.source_count == 1
        assert result.source_titles == ["Biology Lecture"]
        assert len(result.all_concepts) > 0
        
        logger.info(f"✅ merge_cores (1): {result.source_count} source, {len(result.all_concepts)} concepts")
    
    def test_merge_two_cores(self):
        """Test merging two Knowledge Cores."""
        result = self.merger.merge_cores([BIOLOGY_CORE, CHEMISTRY_CORE])
        
        assert isinstance(result, CombinedContext)
        assert result.source_count == 2
        assert "Biology Lecture" in result.source_titles
        assert "Chemistry Lecture" in result.source_titles
        assert len(result.all_concepts) > 0
        assert len(result.unified_summary) > 0
        
        logger.info(f"✅ merge_cores (2): {result.source_count} sources, {len(result.all_concepts)} concepts")
    
    def test_merge_many_cores_hierarchical(self):
        """Test that 4+ cores triggers hierarchical merge."""
        cores = [
            make_mock_core(f"Lecture {i}", [f"Concept {i}"], [f"Fact {i}"])
            for i in range(5)
        ]
        
        result = self.merger.merge_cores(cores)
        
        assert isinstance(result, CombinedContext)
        assert result.source_count == 5
        assert len(result.all_concepts) > 0
        
        logger.info(f"✅ merge_cores (5, hierarchical): {result.source_count} sources")
    
    def test_fallback_summarize_on_error(self):
        """Test that fallback summarization works when LLM fails."""
        # Simulate no API key scenario
        merger_no_llm = CoreMerger.__new__(CoreMerger)
        merger_no_llm.model = None
        
        summary = merger_no_llm._fallback_summarize(BIOLOGY_CORE)
        
        assert isinstance(summary, CoreSummary)
        assert summary.source_title == "Biology Lecture"
        
        logger.info(f"✅ _fallback_summarize: {summary.source_title}")
    
    def test_fallback_merge_on_error(self):
        """Test that fallback merge works when LLM fails."""
        merger_no_llm = CoreMerger.__new__(CoreMerger)
        merger_no_llm.model = None
        
        summaries = [
            CoreSummary(source_title="A", key_concepts=["C1"], key_facts=["F1"], summary="S1", token_estimate=100),
            CoreSummary(source_title="B", key_concepts=["C2"], key_facts=["F2"], summary="S2", token_estimate=100),
        ]
        
        result = merger_no_llm._fallback_merge(summaries)
        
        assert isinstance(result, CombinedContext)
        assert result.source_count == 2
        assert "C1" in result.all_concepts
        assert "C2" in result.all_concepts
        
        logger.info(f"✅ _fallback_merge: {result.source_count} sources")


# =============================================================================
# Integration Tests: GenerateHandler with Multi-Parent
# =============================================================================

class TestMultiParentGeneration:
    """Integration tests for multi-parent generation."""
    
    def test_generate_handler_initialization(self):
        """Test that GenerateHandler initializes with CoreMerger."""
        from backend.handlers.generate_handler import GenerateHandler
        
        handler = GenerateHandler()
        
        assert hasattr(handler, 'core_merger')
        assert handler.core_merger is not None
        
        logger.info("✅ GenerateHandler has core_merger attribute")


# =============================================================================
# Main Runner
# =============================================================================

def run_tests():
    """Run all tests manually."""
    logger.info("=" * 60)
    logger.info("MULTI-PARENT MERGE TEST SUITE")
    logger.info("=" * 60)
    
    # Unit tests
    logger.info("\n--- Unit Tests: CoreMerger ---")
    test = TestCoreMerger()
    test.setup_method()
    
    try:
        test.test_summarize_core_returns_bounded_summary()
        test.test_merge_single_core_passthrough()
        test.test_merge_two_cores()
        test.test_merge_many_cores_hierarchical()
        test.test_fallback_summarize_on_error()
        test.test_fallback_merge_on_error()
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Integration tests
    logger.info("\n--- Integration Tests: GenerateHandler ---")
    test2 = TestMultiParentGeneration()
    
    try:
        test2.test_generate_handler_initialization()
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    logger.info("\n" + "=" * 60)
    logger.info("🎉 ALL TESTS PASSED")
    logger.info("=" * 60)
    return True


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
