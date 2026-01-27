from abc import ABC, abstractmethod
from typing import Optional, Type, Union, Any
from pydantic import BaseModel

class LLMProvider(ABC):
    """
    Abstract interface for LLM providers (Vertex AI, Gemini Studio, OpenAI, etc.).
    """

    @abstractmethod
    def generate_content(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        """
        Generate content from the LLM (Synchronous).
        
        Args:
            prompt: User prompt.
            context: Context text.
            schema: Pydantic model for structured output.
            model_name: Optional model override (e.g. 'gemini-1.5-pro').
        """
        pass

    @abstractmethod
    async def generate_content_async(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        """
        Generate content from the LLM (Asynchronous).
        """
        pass
