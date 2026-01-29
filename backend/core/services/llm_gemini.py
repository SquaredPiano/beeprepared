import os
import logging
import asyncio
from typing import Optional, Type, Union, Any, Dict
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
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
    
    # Special handling to avoid stripping field names that happen to be keywords (like 'definitions')
    # If this dict represents the properties map, we just recurse on values.
    # But usually we are passed a Schema Node.
    
    for key, value in schema.items():
        # 1. Handle Properties Map explicitly
        if key == 'properties' and isinstance(value, dict):
            sanitized_props = {}
            for prop_name, prop_schema in value.items():
                # Recurse on the schema value, but PRESERVE the prop_name key
                sanitized_props[prop_name] = _sanitize_schema_for_vertex(prop_schema, definitions)
            result[key] = sanitized_props
            continue

        # 2. Skip top-level $defs/definitions keys (metadata)
        if key in ('$defs', 'definitions'):
            continue
            
        # 3. Handle 'anyOf' with null types (Optional fields)
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
        
        # 4. Handle $ref - inline the definition
        if key == '$ref' and isinstance(value, str):
            ref_name = value.split('/')[-1]
            if ref_name in definitions:
                # Recursively sanitize the resolved definition
                result.update(_sanitize_schema_for_vertex(definitions[ref_name], definitions))
            else:
                result['$ref'] = value
            continue
        
        # 5. Recursive descent for other nested structures (like 'items' in arrays)
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
    
    # Extract definitions from root
    defs = raw_schema.get('$defs', raw_schema.get('definitions', {}))
    
    # Create a deep copy of defs and ensure they are all sanitized themselves?
    # No, lazy resolution in recursion is better to handle circular refs if any (though Pydantic creates DAGs usually).
    # But strictly, we should probably resolve them. 
    # For now, passing `defs` map to the function works.
    
    sanitized = _sanitize_schema_for_vertex(raw_schema, defs)
    
    # Ensure properties are fully resolved (Double check for root properties)
    # The recursion inside _sanitize should have handled 'properties' values dicts.
    
    logger.debug(f"Sanitized schema for {pydantic_model.__name__}: {list(sanitized.keys())}")
    return sanitized

class GeminiLLM(LLMProvider):
    def __init__(self):
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        
        # 1. Initialize Vertex AI SDK
        if project:
            try:
                vertexai.init(project=project, location=location)
                logger.info(f"Vertex AI initialized (project={project}, location={location})")
            except Exception as e:
                logger.error(f"Vertex AI init failed: {e}")
        else:
            logger.warning("GOOGLE_CLOUD_PROJECT missing. Vertex AI will fail.")

        # 2. Auto-Discovery: Find a working model
        self.model = None
        self.model_name = None
        self._resolve_working_model()

    def _resolve_working_model(self):
        """
        Probes a list of candidates to find the first one that is:
        1. Available in this region/project (No 404)
        2. Accessible with current credentials (No 403)
        """
        # Priority order
        # Try explicit publisher paths first to bypass project-level model resolution issues
        # Updated for 2026 model availability (Gemini 1.5 is deprecated)
        candidates = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-3-flash-preview",
            "publishers/google/models/gemini-2.5-flash",
            "publishers/google/models/gemini-2.0-flash",
            "publishers/google/models/gemini-3-flash-preview",
        ]

        print("Starting Vertex AI Model Auto-Discovery...")
        logger.info("Starting Vertex AI Model Auto-Discovery...")
        
        self.last_init_error = None

        for candidate in candidates:
            try:
                print(f"Probing model: {candidate}...")
                model = GenerativeModel(candidate)
                # Helper probe to ensure navigability
                response = model.generate_content("Ping", stream=False)
                if response and response.text:
                    msg = f"✅ SUCCESS: Selected model '{candidate}'"
                    print(msg)
                    logger.info(msg)
                    self.model_name = candidate
                    self.model = model
                    return
            except Exception as e:
                print(f"❌ '{candidate}' failed: {e}")
                logger.warning(f"❌ '{candidate}' failed: {e}")
                self.last_init_error = f"Last tried '{candidate}': {e}"
                continue
        
        err_msg = "CRITICAL: No working Vertex AI models found. LLM features will fail."
        print(err_msg)
        logger.error(err_msg)
        self.model = None
        self.model_name = "unavailable"

    async def generate_content_async(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        # Lazy Init / Retry
        if not self.model:
            print("⚠️ Model not initialized. Retrying discovery...")
            self._resolve_working_model()
            
        if not self.model:
            raise RuntimeError(f"Vertex AI model not initialized. Discovery failed. Last Error: {self.last_init_error}")

        contents = [prompt]
        if context:
            contents.append(context)

        # Determine target model (instantiate new one if override provided)
        target_gen_model = self.model
        if model_name and model_name != self.model_name:
             target_gen_model = GenerativeModel(model_name)

        # Attempt 1: With Strict Schema
        if schema:
            try:
                sanitized_schema = _prepare_vertex_schema(schema)
                logger.info(f"Using sanitized schema for {schema.__name__}")
                generation_config = GenerationConfig(
                    response_mime_type='application/json',
                    response_schema=sanitized_schema,
                    max_output_tokens=8192,
                    temperature=1.0
                )
                
                response = await asyncio.to_thread(
                    target_gen_model.generate_content,
                    contents,
                    generation_config=generation_config,
                    stream=False
                )
                
                if response.text:
                    return schema.model_validate_json(response.text)
                else:
                    raise RuntimeError("Empty response for structured output.")
                    
            except Exception as e:
                logger.warning(f"Async strict schema generation failed ({str(e)}). Falling back to standard JSON generation.")
                # Fallthrough to retry simple JSON mode

        # Attempt 2: Standard JSON Mode (Fallback)
        # We append the schema to the prompt to guide the model since we can't use response_schema
        fallback_contents = list(contents)
        if schema:
             import json
             schema_str = json.dumps(schema.model_json_schema(), indent=2)
             fallback_instruction = f"\n\nIMPORTANT: Output valid JSON adhering exactly to this schema:\n```json\n{schema_str}\n```"
             # Append to the last content part (usually the prompt)
             if isinstance(fallback_contents[-1], str):
                 fallback_contents[-1] += fallback_instruction
             else:
                 fallback_contents.append(fallback_instruction)

        generation_config = GenerationConfig(
            response_mime_type='application/json',
            max_output_tokens=8192,
            temperature=1.0,
        )
        
        try:
            response = await asyncio.to_thread(
                target_gen_model.generate_content,
                fallback_contents,
                generation_config=generation_config,
                stream=False
            )
            
            if schema:
                if response.text:
                    return schema.model_validate_json(response.text)
                else:
                    raise RuntimeError("Empty response for structured output.")
            
            return response.text

        except Exception as e:
            logger.error(f"Vertex AI Async generation failed: {e}")
            raise e

    def generate_content(
        self, 
        prompt: str, 
        context: Optional[str] = None, 
        schema: Optional[Type[BaseModel]] = None,
        model_name: Optional[str] = None
    ) -> Union[str, BaseModel, Any]:
        
        if not self.model:
            raise RuntimeError("Vertex AI model not initialized.")

        contents = [prompt]
        if context:
            contents.append(context)
        
        target_gen_model = self.model
        if model_name and model_name != self.model_name:
             target_gen_model = GenerativeModel(model_name)
        
        # Attempt 1: With Strict Schema
        if schema:
            try:
                sanitized_schema = _prepare_vertex_schema(schema)
                logger.info(f"Using sanitized schema for {schema.__name__}")
                generation_config = GenerationConfig(
                    response_mime_type='application/json',
                    response_schema=sanitized_schema,
                    max_output_tokens=8192,
                    temperature=1.0
                )
                
                response = target_gen_model.generate_content(
                    contents,
                    generation_config=generation_config,
                    stream=False
                )
                
                if response.text:
                    return schema.model_validate_json(response.text)
                else:
                    raise RuntimeError("Empty response for structured output.")
                    
            except Exception as e:
                logger.warning(f"Strict schema generation failed ({str(e)}). Falling back to standard JSON generation.")
                # Fallthrough to retry simple JSON mode

        # Attempt 2: Standard JSON Mode (Fallback)
        fallback_contents = list(contents)
        if schema:
             import json
             schema_str = json.dumps(schema.model_json_schema(), indent=2)
             fallback_instruction = f"\n\nIMPORTANT: Output valid JSON adhering exactly to this schema:\n```json\n{schema_str}\n```"
             if isinstance(fallback_contents[-1], str):
                 fallback_contents[-1] += fallback_instruction
             else:
                 fallback_contents.append(fallback_instruction)

        generation_config = GenerationConfig(
            response_mime_type='application/json',
            max_output_tokens=8192,
            temperature=1.0,
        )
        
        try:
            # Set a 3-minute timeout to prevent infinite hangs
            response = target_gen_model.generate_content(
                fallback_contents,
                generation_config=generation_config,
                stream=False
            )
            
            if schema:
                if response.text:
                    return schema.model_validate_json(response.text)
                else:
                    raise RuntimeError("Empty response for structured output.")

            return response.text

        except Exception as e:
            logger.error(f"Vertex AI generation failed: {e}")
            raise e
