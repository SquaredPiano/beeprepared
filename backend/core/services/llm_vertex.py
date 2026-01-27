import os
import logging
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from typing import Optional, Type, Union, Any
from pydantic import BaseModel
from backend.core.llm_interface import LLMProvider

logger = logging.getLogger(__name__)

class VertexLLM(LLMProvider):
    def __init__(self):
        self.project_id = os.getenv("VERTEX_PROJECT_ID")
        self.location = os.getenv("VERTEX_LOCATION", "us-central1")
        self.model_name = os.getenv("VERTEX_MODEL", "gemini-1.5-flash") # Stable alias
        self.api_key = os.getenv("VERTEX_API_KEY") # Optional, if user uses API Key with Vertex

        if not self.project_id:
             # Try to infer from default credentials or warn
             logger.warning("VERTEX_PROJECT_ID not set. Vertex AI might fail if not running in GCP.")

        try:
            # Explicitly load credentials if available
            # This is critical for local/docker environments where ADC might not be auto-detected correctly by the async client
            from google.oauth2 import service_account
            creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            credentials = None
            
            if creds_path and os.path.exists(creds_path):
                credentials = service_account.Credentials.from_service_account_file(creds_path)
            
            vertexai.init(project=self.project_id, location=self.location, credentials=credentials)
            
            self.model = GenerativeModel(self.model_name)
            logger.info(f"Vertex AI initialized with model: {self.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Vertex AI: {e}")
            self.model = None

    def _get_model(self, model_name: Optional[str] = None):
        if not model_name:
            return self.model
        # Create a temporary instance for this request
        return GenerativeModel(model_name)

    def generate_content(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        model = self._get_model(model_name)
        if not model:
            raise RuntimeError("Vertex AI model not initialized.")

        full_prompt = [prompt]
        if context:
            full_prompt.append(context)

        config = {}
        if schema:
            config = GenerationConfig(
                response_mime_type="application/json",
                response_schema=schema.model_json_schema()
            )
        
        try:
            response = model.generate_content(
                full_prompt,
                generation_config=config
            )
            return self._parse_response(response, schema)

        except Exception as e:
            logger.error(f"Vertex AI generation failed: {e}")
            raise e

    async def generate_content_async(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        model = self._get_model(model_name)
        if not model:
            raise RuntimeError("Vertex AI model not initialized.")

        full_prompt = [prompt]
        if context:
            full_prompt.append(context)

        config = {}
        if schema:
            config = GenerationConfig(
                response_mime_type="application/json",
                response_schema=schema.model_json_schema()
            )
        
        try:
            # Async generation
            response = await model.generate_content_async(
                full_prompt,
                generation_config=config
            )
            return self._parse_response(response, schema)

        except Exception as e:
            logger.error(f"Vertex AI Async generation failed: {e}")
            raise e

    def _parse_response(self, response, schema):
        text_response = response.text
        if schema:
            try:
                return schema.model_validate_json(text_response)
            except Exception as parse_error:
                logger.error(f"Failed to parse Vertex AI response to schema: {parse_error}")
                # logger.debug(f"Raw response: {text_response}")
                raise parse_error
        return text_response
