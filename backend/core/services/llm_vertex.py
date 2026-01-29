import os
import logging
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from typing import Optional, Type, Union, Any, Dict, List
from pydantic import BaseModel
from backend.core.llm_interface import LLMProvider

logger = logging.getLogger(__name__)

def _sanitize_schema_for_vertex(schema: Dict[str, Any], definitions: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Converts a Pydantic JSON schema to Vertex AI-compatible format.
    Recursively inlines $refs and removes unsupported types (null).
    """
    if not isinstance(schema, dict):
        return schema
    
    if definitions is None:
        definitions = {}
    
    result = {}
    
    for key, value in schema.items():
        # Skip $defs/definitions keys - we use the passed 'definitions' map
        if key in ('$defs', 'definitions'):
            continue
            
        # Handle 'anyOf' with null types (Optional fields)
        if key == 'anyOf' and isinstance(value, list):
            # Filter out null types
            non_null_types = [t for t in value if not (isinstance(t, dict) and t.get('type') == 'null')]
            
            if len(non_null_types) == 1:
                # Single type remaining - flatten anyOf
                result.update(_sanitize_schema_for_vertex(non_null_types[0], definitions))
            elif len(non_null_types) > 1:
                # Multiple non-null types
                result['anyOf'] = [_sanitize_schema_for_vertex(t, definitions) for t in non_null_types]
            continue
        
        # Handle $ref - inline the definition
        if key == '$ref' and isinstance(value, str):
            ref_name = value.split('/')[-1]
            if ref_name in definitions:
                # Recursively sanitize the resolved definition
                result.update(_sanitize_schema_for_vertex(definitions[ref_name], definitions))
            else:
                # If we can't resolve it, keep it
                result['$ref'] = value
            continue
        
        # Recursively sanitize nested objects
        if isinstance(value, dict):
            result[key] = _sanitize_schema_for_vertex(value, definitions)
        elif isinstance(value, list):
            result[key] = [_sanitize_schema_for_vertex(item, definitions) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
            
    return result

def _prepare_vertex_schema(pydantic_model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Prepares a Pydantic model's JSON schema for use with Vertex AI.
    extracts definitions and recursively inlines them.
    """
    raw_schema = pydantic_model.model_json_schema()
    defs = raw_schema.get('$defs', raw_schema.get('definitions', {}))
    
    sanitized = _sanitize_schema_for_vertex(raw_schema, defs)
    
    logger.debug(f"Sanitized schema for {pydantic_model.__name__}: {list(sanitized.keys())}")
    return sanitized

class VertexLLM(LLMProvider):
    def __init__(self):
        self.project_id = os.getenv("VERTEX_PROJECT_ID")
        self.location = os.getenv("VERTEX_LOCATION", "us-central1")
        self.model_name = os.getenv("VERTEX_MODEL", "gemini-2.5-flash") # Stable alias
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

        # With Schema: Use JSON mode with structured output
        if schema:
            try:
                vertex_schema = _prepare_vertex_schema(schema)
                config = GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=vertex_schema
                )
                response = model.generate_content(
                    full_prompt,
                    generation_config=config
                )
                return self._parse_response(response, schema)
            except Exception as e:
                logger.warning(f"Strict schema generation failed ({str(e)}). Falling back to JSON without schema constraint.")
                # Fallback: JSON mode without schema
                try:
                    config = GenerationConfig(
                        response_mime_type="application/json"
                    )
                    response = model.generate_content(
                        full_prompt,
                        generation_config=config
                    )
                    return self._parse_response(response, schema)
                except Exception as e2:
                    logger.error(f"JSON fallback also failed: {e2}")
                    raise e2

        # No Schema: Plain text generation (for notes, etc.)
        try:
            response = model.generate_content(full_prompt)
            return response.text

        except Exception as e:
            logger.error(f"Vertex AI text generation failed: {e}")
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

        # With Schema: Use JSON mode with structured output
        if schema:
            try:
                vertex_schema = _prepare_vertex_schema(schema)
                config = GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=vertex_schema
                )
                response = await model.generate_content_async(
                    full_prompt,
                    generation_config=config
                )
                return self._parse_response(response, schema)
            except Exception as e:
                logger.warning(f"Async strict schema generation failed ({str(e)}). Falling back to JSON without schema constraint.")
                # Fallback: JSON mode without schema
                try:
                    config = GenerationConfig(
                        response_mime_type="application/json"
                    )
                    response = await model.generate_content_async(
                        full_prompt,
                        generation_config=config
                    )
                    return self._parse_response(response, schema)
                except Exception as e2:
                    logger.error(f"Async JSON fallback also failed: {e2}")
                    raise e2

        # No Schema: Plain text generation (for notes, etc.)
        try:
            response = await model.generate_content_async(full_prompt)
            return response.text

        except Exception as e:
            logger.error(f"Vertex AI Async text generation failed: {e}")
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
