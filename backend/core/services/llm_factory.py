import os
import logging
from backend.core.llm_interface import LLMProvider
from backend.core.services.llm_vertex import VertexLLM
from backend.core.services.llm_gemini import GeminiLLM

logger = logging.getLogger(__name__)

class LLMFactory:
    @staticmethod
    def get_provider() -> LLMProvider:
        """
        Returns an instance of LLMProvider based on configuration.
        """
        provider_type = os.getenv("LLM_PROVIDER", "vertex").lower()
        
        if provider_type == "vertex":
            logger.info("Using Vertex AI Provider")
            return VertexLLM()
        elif provider_type == "gemini":
            logger.info("Using Gemini (AI Studio) Provider")
            return GeminiLLM()
        else:
            logger.warning(f"Unknown LLM_PROVIDER '{provider_type}', defaulting to Vertex AI")
            return VertexLLM()
