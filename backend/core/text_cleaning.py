import re
import os
import logging
import asyncio
from dotenv import load_dotenv
from backend.core.services.llm_factory import LLMFactory

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

class TextCleaningService:
    def __init__(self):
        self._setup_llm()

    def _setup_llm(self):
        """Initialize LLM Provider via Factory."""
        try:
            self.llm = LLMFactory.get_provider()
        except Exception as e:
            logger.warning(f"Failed to initialize LLM Provider for cleaning: {e}. LLM cleaning will be skipped.")
            self.llm = None

    def clean_regex(self, text: str) -> str:
        """
        Performs fast, rule-based cleaning using Regex. (Synchronous CPU bound)
        """
        if not text:
            return ""

        # 1. Remove Timestamps
        text = re.sub(r'\b\d{1,2}:\d{2}(:\d{2})?\b', '', text)
        # 2. Remove Speaker Labels
        text = re.sub(r'\b[A-Z]+:\s*', '', text)
        # 3. Remove Parentheticals
        text = re.sub(r'\([^\)]+\)', '', text)
        text = re.sub(r'\[[^\]]+\]', '', text)
        # 4. Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        # 5. Remove filler words
        fillers = [r'\bum\b', r'\buh\b', r'\bah\b', r'\ber\b', r'\bhmm\b']
        for filler in fillers:
            text = re.sub(filler, '', text, flags=re.IGNORECASE)
        # 6. Handle "like"
        text = re.sub(r'\blike\s+', ' ', text, flags=re.IGNORECASE)
        # 7. Fix punctuation
        text = re.sub(r'\s+([.,!?;:])', r'\1', text)
        text = re.sub(r'\.+', '.', text)

        return text.strip()

    async def clean_chunk(self, chunk: str, index: int) -> str:
        """Process a single chunk with LLM."""
        if not chunk.strip():
            return ""
            
        prompt = f"""
        You are an expert editor. Fix grammar, transcription errors, and standardize terms.
        Keep meaning identical. Do NOT summarize. Output PLAIN TEXT only.
        Raw Text:
        {chunk}
        """
        try:
            # Use FLASH for speed on chunks
            # Use configured default model (usually flash) instead of hardcoded
            response = await self.llm.generate_content_async(
                prompt, 
                model_name=None 
            )
            
            if response and isinstance(response, str):
                return self._strip_markdown_artifacts(response.strip())
            return chunk
        except Exception as e:
            logger.error(f"Chunk {index} failed: {e}")
            return chunk

    async def clean_with_llm(self, text: str) -> str:
        """
        Uses LLM (Vertex/Gemini) to fix text in PARALLEL chunks.
        """
        if not self.llm:
            logger.warning("LLM provider not initialized. Skipping LLM cleaning.")
            return text

        logger.info("Starting Parallel LLM Cleaning...")
        
        # Split into chunks of ~4000 chars (approx 1000 tokens)
        chunk_size = 4000
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        logger.info(f"Split text into {len(chunks)} chunks.")
        
        tasks = [self.clean_chunk(chunk, i) for i, chunk in enumerate(chunks)]
        
        # Execute in parallel
        results = await asyncio.gather(*tasks)
        
        # Join results
        cleaned_text = " ".join(results)
        
        # Final whitespace cleanup
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        return cleaned_text
    
    def _strip_markdown_artifacts(self, text: str) -> str:
        """Remove markdown artifacts."""
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        text = re.sub(r'```[^`]*```', '', text)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'(?<!\w)\*+(?!\w)', ' ', text)
        text = re.sub(r'(?<!\w)_+(?!\w)', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    async def clean_text(self, text: str, use_llm: bool = True) -> str:
        """
        Main orchestration method for text cleaning (Async).
        """
        logger.info("Starting text cleaning...")
        
        # 1. Regex Pass (Fast Sync)
        cleaned_text = self.clean_regex(text)
        
        # 2. LLM Pass (Async Parallel)
        if use_llm and self.llm:
            cleaned_text = await self.clean_with_llm(cleaned_text)
            
        logger.info("Text cleaning completed.")
        return cleaned_text

if __name__ == "__main__":
    # Test Block
    cleaner = TextCleaningService()
    raw_input = "Transcript sample..."
    
    async def run_test():
        res = await cleaner.clean_text(raw_input)
        print(f"Result: {res}")
        
    import asyncio
    asyncio.run(run_test())
