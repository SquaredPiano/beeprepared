import os
import logging
import json
from typing import Optional, Type, Union, Any, Dict
from pydantic import BaseModel
from google import genai
from google.genai import types
from backend.core.llm_interface import LLMProvider
from backend.env import load_environment

logger = logging.getLogger(__name__)

class GeminiLLM(LLMProvider):
    def __init__(self):
        load_environment()
        self.model_name = (
            os.getenv("GEMINI_MODEL")
            or os.getenv("VERTEX_MODEL")
            or "gemini-2.5-flash"
        )
        self.api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("VERTEX_API_KEY")
        )
        self.project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("VERTEX_PROJECT_ID")
        self.location = (
            os.getenv("GOOGLE_CLOUD_LOCATION")
            or os.getenv("VERTEX_LOCATION")
            or "us-central1"
        )
        self.using_vertex = False
        self.client = self._create_client()

    def _create_client(self):
        if self.api_key:
            logger.info("Gemini API client initialized with API key.")
            return genai.Client(api_key=self.api_key)

        return self._create_vertex_client()

    def _create_vertex_client(self):
        if self.project:
            credentials = None
            creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if creds_path and os.path.exists(creds_path):
                from google.oauth2 import service_account

                credentials = service_account.Credentials.from_service_account_file(
                    creds_path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )

            self.using_vertex = True
            self.model_name = os.getenv("VERTEX_MODEL") or "gemini-2.5-flash"
            logger.info(
                "Gemini Vertex client initialized "
                f"(project={self.project}, location={self.location})."
            )
            return genai.Client(
                vertexai=True,
                project=self.project,
                location=self.location,
                credentials=credentials,
            )

        raise RuntimeError(
            "Missing Gemini configuration. Set GEMINI_API_KEY, GOOGLE_API_KEY, "
            "VERTEX_API_KEY, or GOOGLE_CLOUD_PROJECT/VERTEX_PROJECT_ID."
        )

    def _try_vertex_fallback(self, error: Exception) -> bool:
        message = str(error)
        invalid_api_key = "API_KEY_INVALID" in message or "API key not valid" in message
        if not invalid_api_key or self.using_vertex or not self.project:
            return False

        logger.warning("Gemini API key was rejected; retrying with Vertex credentials.")
        self.client = self._create_vertex_client()
        return True

    def _contents(self, prompt: str, context: Optional[str] = None) -> list[str]:
        contents = [prompt]
        if context:
            contents.append(context)
        return contents

    def _config(
        self,
        schema: Optional[Type[BaseModel]] = None,
        *,
        strict_schema: bool = True,
    ) -> types.GenerateContentConfig:
        kwargs: Dict[str, Any] = {
            "max_output_tokens": 8192,
            "temperature": 1.0,
        }
        if schema:
            kwargs["response_mime_type"] = "application/json"
            if strict_schema:
                kwargs["response_schema"] = schema
        return types.GenerateContentConfig(**kwargs)

    def _with_schema_instruction(self, contents: list[str], schema: Type[BaseModel]) -> list[str]:
        fallback_contents = list(contents)
        schema_str = json.dumps(schema.model_json_schema(), indent=2)
        instruction = (
            "\n\nIMPORTANT: Output valid JSON adhering exactly to this schema:\n"
            f"```json\n{schema_str}\n```"
        )
        fallback_contents[-1] += instruction
        return fallback_contents

    def _parse_response(self, response: Any, schema: Optional[Type[BaseModel]] = None):
        if not schema:
            return response.text

        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if isinstance(parsed, schema):
                return parsed
            return schema.model_validate(parsed)

        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if not text:
            raise RuntimeError("Empty response for structured output.")

        try:
            return schema.model_validate_json(text)
        except Exception:
            return schema.model_validate(json.loads(text))

    async def generate_content_async(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        contents = self._contents(prompt, context)
        target_model = model_name or self.model_name

        # Attempt 1: With Strict Schema
        if schema:
            try:
                logger.info(f"Using structured schema for {schema.__name__}")
                response = await self.client.aio.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=self._config(schema, strict_schema=True),
                )
                return self._parse_response(response, schema)
            except Exception as e:
                if self._try_vertex_fallback(e):
                    return await self.generate_content_async(prompt, context, schema, model_name)
                logger.warning(f"Async strict schema generation failed ({str(e)}). Falling back to standard JSON generation.")
                # Fallthrough to retry simple JSON mode

        # Attempt 2: Standard JSON Mode (Fallback)
        # We append the schema to the prompt to guide the model since we can't use response_schema
        fallback_contents = self._with_schema_instruction(contents, schema) if schema else contents
        
        try:
            response = await self.client.aio.models.generate_content(
                model=target_model,
                contents=fallback_contents,
                config=self._config(schema, strict_schema=False),
            )
            return self._parse_response(response, schema)

        except Exception as e:
            if self._try_vertex_fallback(e):
                return await self.generate_content_async(prompt, context, schema, model_name)
            logger.error(f"Gemini async generation failed: {e}")
            raise e

    def generate_content(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        contents = self._contents(prompt, context)
        target_model = model_name or self.model_name
        
        # Attempt 1: With Strict Schema
        if schema:
            try:
                logger.info(f"Using structured schema for {schema.__name__}")
                response = self.client.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=self._config(schema, strict_schema=True),
                )
                return self._parse_response(response, schema)
            except Exception as e:
                if self._try_vertex_fallback(e):
                    return self.generate_content(prompt, context, schema, model_name)
                logger.warning(f"Strict schema generation failed ({str(e)}). Falling back to standard JSON generation.")
                # Fallthrough to retry simple JSON mode

        # Attempt 2: Standard JSON Mode (Fallback)
        fallback_contents = self._with_schema_instruction(contents, schema) if schema else contents
        
        try:
            response = self.client.models.generate_content(
                model=target_model,
                contents=fallback_contents,
                config=self._config(schema, strict_schema=False),
            )
            return self._parse_response(response, schema)

        except Exception as e:
            if self._try_vertex_fallback(e):
                return self.generate_content(prompt, context, schema, model_name)
            logger.error(f"Gemini generation failed: {e}")
            raise e
