"""
Test extraction service with all file formats.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extraction import ExtractionService

# Test files
TEST_FILES = [
    ("temp/documents_3fcfbc51-98ef-4f65-a39d-48812c6121ee.md", "Markdown"),
    ("temp/documents_2e653fb4-4919-4ef0-970a-795f885bf7ff.pdf", "PDF"),
    ("temp/documents_3fc1b196-2386-47cc-ad36-88d269c504d6.pptx", "PowerPoint"),
    ("temp/uploads_0fb93a80-3397-40e7-bcac-9c97d43d82be.wav", "Audio (WAV)"),
    ("temp/Lumen - TerraHacks 2025 Project Demonstration.mp4", "Video (MP4)"),
]


def test_extraction():
    print("\n" + "="*70)
    print("  BeePrepared - Extraction Service Test")
    print("="*70)
    
    service = ExtractionService()
    results = {}
    
    for file_path, file_type in TEST_FILES:
        full_path = os.path.join(os.path.dirname(__file__), "..", file_path)
        
        print(f"\n{'─'*70}")
        print(f"📁 Testing {file_type}: {os.path.basename(file_path)}")
        print(f"{'─'*70}")
        
        if not os.path.exists(full_path):
            print(f"   ⚠️  File not found: {full_path}")
            results[file_type] = {"status": "SKIPPED", "reason": "File not found"}
            continue
        
        try:
            text, metadata = service.extract(full_path)
            
            # Show results
            print(f"   ✅ SUCCESS")
            print(f"   📊 Metadata:")
            for key, value in metadata.items():
                print(f"      {key}: {value}")
            
            # Preview text
            preview = text[:500].replace('\n', ' ')
            print(f"   📝 Preview: {preview}...")
            
            results[file_type] = {
                "status": "PASS",
                "word_count": metadata.get("word_count", 0),
                "extraction_time": metadata.get("extraction_time_seconds", 0)
            }
            
        except Exception as e:
            print(f"   ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[file_type] = {"status": "FAIL", "error": str(e)}
    
    # Summary
    print(f"\n{'='*70}")
    print("  SUMMARY")
    print(f"{'='*70}")
    
    passed = 0
    failed = 0
    skipped = 0
    
    for file_type, result in results.items():
        status = result["status"]
        if status == "PASS":
            emoji = "✅"
            passed += 1
            extra = f"({result['word_count']} words, {result['extraction_time']}s)"
        elif status == "FAIL":
            emoji = "❌"
            failed += 1
            extra = f"({result.get('error', 'Unknown error')})"
        else:
            emoji = "⚠️"
            skipped += 1
            extra = f"({result.get('reason', 'Skipped')})"
        
        print(f"   {emoji} {file_type}: {status} {extra}")
    
    print(f"\n   Total: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed == 0 and passed > 0:
        print("\n🐝 All available tests passed! Extraction service is ready!")
    elif failed > 0:
        print("\n⚠️  Some tests failed. Check the errors above.")
    
    return failed == 0


if __name__ == "__main__":
    success = test_extraction()
    sys.exit(0 if success else 1)
