import os
import logging
from google import genai
from typing import Optional, Type, Union, Any
from pydantic import BaseModel
from backend.core.llm_interface import LLMProvider

logger = logging.getLogger(__name__)

class GeminiLLM(LLMProvider):
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        
        if self.api_key:
            try:
                self.client = genai.Client(api_key=self.api_key)
                logger.info(f"Gemini (AI Studio) initialized with model: {self.model_name}")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                self.client = None
        else:
            logger.warning("GEMINI_API_KEY not found. Gemini LLM will fail.")
            self.client = None

    async def generate_content_async(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        if not self.client:
            raise RuntimeError("Gemini client not initialized.")

        contents = [prompt]
        if context:
            contents.append(context)

        config = {}
        if schema:
            config = {
                'response_mime_type': 'application/json',
                'response_schema': schema
            }
        
        target_model = model_name or self.model_name
        
        try:
            # Use async client if available or wrap sync?
            # google.genai.Client supports async via `client.aio`
            if hasattr(self.client, 'aio'):
                response = await self.client.aio.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=config
                )
            else:
                # Fallback if no aio property (should exist in new SDK)
                # Or run in executor
                import asyncio
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, 
                    lambda: self.client.models.generate_content(
                        model=target_model, contents=contents, config=config
                    )
                )

            if schema and response.parsed:
                return response.parsed
            elif schema and not response.parsed:
                raise RuntimeError("Failed to parse structured output from Gemini.")
            
            return response.text

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise e

    def generate_content(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        if not self.client:
            raise RuntimeError("Gemini client not initialized.")

        contents = [prompt]
        if context:
            contents.append(context)

        config = {}
        if schema:
            config = {
                'response_mime_type': 'application/json',
                'response_schema': schema
            }
        
        target_model = model_name or self.model_name
        
        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=contents,
                config=config
            )
            
            if schema and response.parsed:
                return response.parsed
            elif schema and not response.parsed:
                raise RuntimeError("Failed to parse structured output from Gemini.")
            return response.text

        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise e
