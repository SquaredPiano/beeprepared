import os
import sys
import time
import logging
from typing import Optional

# Ensure backend root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.core.ingest import IngestionService
from backend.core.extraction import ExtractionService
from backend.core.text_cleaning import TextCleaningService
from backend.core.knowledge_core import KnowledgeCoreService

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PipelineTester:
    def __init__(self):
        self.ingest = IngestionService()
        self.extract = ExtractionService()
        # Initialize cleaner with LLM disabled for speed/cost if desired, but let's default to True for full test
        self.cleaner = TextCleaningService() 
        self.core_service = KnowledgeCoreService()
        self.user_id = "test_user_pipeline"
    
    def run_pipeline(self, file_path: Optional[str], file_url: Optional[str], input_type: str) -> bool:
        """
        Runs the full pipeline for a given input.
        Returns True if successful, False otherwise.
        """
        print("\n" + "="*60)
        print(f"TESTING PIPELINE: {input_type}")
        print("="*60)
        
        try:
            # --- STEP 1: INGEST ---
            start = time.time()
            metadata = {}
            r2_key = ""
            
            if input_type == "YOUTUBE":
                if not file_url:
                    print("❌ Failure: No URL provided for YouTube test.")
                    return False
                print(f"Step 1: Ingesting YouTube URL: {file_url}")
                metadata = self.ingest.process_youtube(file_url, self.user_id)
                
            elif input_type == "AUDIO":
                if not file_path: return False
                print(f"Step 1: Ingesting Audio File: {file_path}")
                metadata = self.ingest.process_audio_upload(file_path, self.user_id, os.path.basename(file_path))
                
            elif input_type == "VIDEO":
                if not file_path: return False
                print(f"Step 1: Ingesting Video File: {file_path}")
                metadata = self.ingest.process_video_upload(file_path, self.user_id, os.path.basename(file_path))
                
            elif input_type in ["PDF", "PPTX", "MD", "TXT"]:
                if not file_path: return False
                print(f"Step 1: Ingesting Document ({input_type}): {file_path}")
                input_ext = input_type.lower() if input_type != "TXT" else "txt" # Mapping doc_type string to what ingest expects
                # Ingest expects "pdf", "pptx", "md" etc.
                metadata = self.ingest.process_document(file_path, self.user_id, os.path.basename(file_path), input_ext)
            
            # Validation
            if metadata.get("status") == "FAILED":
                print(f"❌ Ingest Failed: {metadata}")
                return False
                
            r2_key = metadata.get("fileURL")
            if not r2_key:
                print("❌ Ingest returned no fileURL (R2 Key).")
                return False
                
            print(f"✅ Ingest Success. R2 Key: {r2_key}")
            
            # --- STEP 2: EXTRACT ---
            print(f"Step 2: Extracting from R2 Key: {r2_key}")
            raw_text, extract_meta = self.extract.extract_from_r2(r2_key)
            
            if not raw_text or len(raw_text.strip()) == 0:
                print("❌ Extraction returned empty text.")
                return False
            
            print(f"✅ Extraction Success. {len(raw_text)} chars extracted.")
            # print(f"Preview: {raw_text[:100]}...")
            
            # --- STEP 3: CLEAN ---
            print(f"Step 3: Cleaning Text (LLM enabled)...")
            # Might verify if cleaner works fast enough with LLM, maybe skip for big files 
            # or just regex if we want speed text. Let's try full.
            clean_text = self.cleaner.clean_text(raw_text, use_llm=True)
            
            if not clean_text:
                print("❌ Cleaning returned empty text.")
                return False
                
            print(f"✅ Cleaning Success. {len(clean_text)} chars.")
            
            # --- STEP 4: KNOWLEDGE CORE ---
            print(f"Step 4: Generating Knowledge Core...")
            core = self.core_service.generate_knowledge_core(clean_text)
            
            if not core:
                print("❌ Knowledge Core generation failed.")
                return False
                
            print(f"✅ Knowledge Core Success.")
            print(f"   Title: {core.title}")
            print(f"   Concepts: {len(core.concepts)}")
            print(f"   Sections: {len(core.section_hierarchy)}")
            
            elapsed = time.time() - start
            print(f"\n🎉 PIPELINE PASS for {input_type} in {elapsed:.2f}s")
            return True
            
        except Exception as e:
            print(f"❌ CRITICAL FAILURE: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == "__main__":
    tester = PipelineTester()
    
    # Define Test Cases
    # Verify these paths on your system before running!
    
    # 1. YouTube (Short video for speed test)
    # Using a short TED talk or similar public domain if possible. 
    # Example: "Math is the hidden secret to understanding the world" (Short)
    yt_url = "https://www.youtube.com/watch?v=YeSzeu12FIs" # Just a placeholder valid URL, or use user's choice
    # Actually, let's use a very short video: "Test Video 10s"
    # yt_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw" # Me at the zoo (short)
    
    # 2. Local Files. 
    # We will look for files in backend/ or generate dummies if simple.
    # Generating dummy text files is easy. Dummy PDF/PPTX is harder without libs.
    # We'll assert existence.
    
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
    
    # Create a dummy MD file
    md_path = os.path.join(base_path, "backend", "test_doc.md")
    with open(md_path, "w") as f:
        f.write("# Integration Test Document\n\nThis is a test of the BeePrepared pipeline.\n\n## Subheading\n\nIt should extract structure and concepts.")

    # Create dummy TXT
    txt_path = os.path.join(base_path, "backend", "test_file.txt")
    with open(txt_path, "w") as f:
        f.write("Simple text file content for verification.")

    results = {}
    
    # --- RUN TESTS ---
    
    # MD
    results["MD"] = tester.run_pipeline(md_path, None, "MD")
    
    # TXT (Mapped to 'text' internally usually)
    results["TXT"] = tester.run_pipeline(txt_path, None, "TXT")
    
    # YouTube (Takes longer due to network)
    # results["YOUTUBE"] = tester.run_pipeline(None, yt_url, "YOUTUBE")
    
    # For PDF/PPTX/Audio/Video, we need real files.
    # Checking for sample.pdf
    pdf_path = os.path.join(base_path, "backend", "sample.pdf")
    if os.path.exists(pdf_path):
        results["PDF"] = tester.run_pipeline(pdf_path, None, "PDF")
    else:
        print("⚠️ Skipping PDF test (sample.pdf not found)")
        
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    for k, v in results.items():
        status = "PASS" if v else "FAIL"
        print(f"{k}: {status}")
    
    # Cleanup dummies
    if os.path.exists(md_path): os.remove(md_path)
    if os.path.exists(txt_path): os.remove(txt_path)
