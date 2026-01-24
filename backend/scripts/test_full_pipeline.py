"""
Test the complete BeePrepared processing pipeline:
Extract → Clean → Generate Knowledge Core

This verifies all backend components work together.
"""
import os
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction import ExtractionService
from text_cleaning import TextCleaningService
from knowledge_core import KnowledgeCoreService


def test_full_pipeline(file_path: str):
    """
    Run a file through the complete processing pipeline.
    """
    print("\n" + "="*70)
    print("  BeePrepared - Full Pipeline Test")
    print("="*70)
    print(f"File: {file_path}")
    
    if not os.path.exists(file_path):
        print(f"\n❌ File not found: {file_path}")
        return False
    
    try:
        # =====================================================================
        # STAGE 1: EXTRACTION
        # =====================================================================
        print(f"\n{'─'*70}")
        print("STAGE 1: EXTRACTION (File → Raw Text)")
        print(f"{'─'*70}")
        
        extractor = ExtractionService()
        raw_text, metadata = extractor.extract(file_path)
        
        print(f"✅ Extracted {metadata['word_count']} words in {metadata['extraction_time_seconds']}s")
        print(f"   File type: {metadata['file_type']}")
        print(f"   Preview: {raw_text[:200]}...")
        
        # =====================================================================
        # STAGE 2: CLEANING
        # =====================================================================
        print(f"\n{'─'*70}")
        print("STAGE 2: CLEANING (Raw Text → Clean Text)")
        print(f"{'─'*70}")
        
        cleaner = TextCleaningService()
        
        # Test with and without LLM
        cleaned_text_regex = cleaner.clean_regex(raw_text)
        print(f"✅ Regex cleaning complete")
        print(f"   Before: {len(raw_text)} chars")
        print(f"   After:  {len(cleaned_text_regex)} chars")
        
        # Full cleaning with LLM (if available)
        cleaned_text_full = cleaner.clean_text(raw_text, use_llm=True)
        print(f"✅ Full cleaning (with LLM) complete")
        print(f"   Final length: {len(cleaned_text_full)} chars")
        print(f"   Preview: {cleaned_text_full[:200]}...")
        
        # =====================================================================
        # STAGE 3: KNOWLEDGE CORE GENERATION
        # =====================================================================
        print(f"\n{'─'*70}")
        print("STAGE 3: KNOWLEDGE CORE (Clean Text → Structured Knowledge)")
        print(f"{'─'*70}")
        
        kg_service = KnowledgeCoreService()
        
        # Use first 5000 chars to avoid token limits in tests
        sample_text = cleaned_text_full[:5000]
        knowledge_core = kg_service.generate_knowledge_core(sample_text)
        
        if knowledge_core:
            print(f"✅ Knowledge Core generated successfully")
            print(f"   Title: {knowledge_core.title}")
            print(f"   Concepts: {len(knowledge_core.concepts)}")
            print(f"   Sections: {len(knowledge_core.section_hierarchy)}")
            print(f"   Definitions: {len(knowledge_core.definitions)}")
            print(f"   Examples: {len(knowledge_core.examples)}")
            print(f"   Key Facts: {len(knowledge_core.key_facts)}")
            print(f"   Notes: {len(knowledge_core.notes)}")
            
            # Show first concept
            if knowledge_core.concepts:
                first_concept = knowledge_core.concepts[0]
                print(f"\n   First Concept: {first_concept.name}")
                print(f"   - {first_concept.description[:100]}...")
        else:
            print(f"⚠️  Knowledge Core generation skipped (check GEMINI_API_KEY)")
        
        # =====================================================================
        # SUMMARY
        # =====================================================================
        print(f"\n{'='*70}")
        print("PIPELINE SUMMARY")
        print(f"{'='*70}")
        print(f"✅ Stage 1: Extraction    ({metadata['word_count']} words)")
        print(f"✅ Stage 2: Cleaning      ({len(cleaned_text_full)} chars)")
        print(f"{'✅' if knowledge_core else '⚠️ '} Stage 3: Knowledge Core ({'Generated' if knowledge_core else 'Skipped'})")
        print()
        
        return True
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    # Default test file
    test_file = "temp/documents_3fcfbc51-98ef-4f65-a39d-48812c6121ee.md"
    
    # Allow custom file from command line
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    
    success = test_full_pipeline(
        os.path.join(os.path.dirname(__file__), "..", test_file)
    )
    
    if success:
        print("🐝 Pipeline test complete!")
    else:
        print("❌ Pipeline test failed!")
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
