
import json
import logging
import sys
from typing import Mapping

# Add backend to path
sys.path.append('.')

from backend.models.artifacts import FlashcardModel, ExamQuestion, FinalExamModel
from backend.core.services.llm_gemini import _prepare_vertex_schema

# Setup logging
logging.basicConfig(level=logging.DEBUG)

def test_schema_generation(model_class):
    print(f"\n--- Testing {model_class.__name__} ---")
    
    # 1. Raw Pydantic Schema
    raw_schema = model_class.model_json_schema()
    print(f"Ref Keys in $defs: {list(raw_schema.get('$defs', {}).keys())}")
    
    # Check for references
    def find_refs(obj):
        refs = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == '$ref':
                    refs.append(v)
                else:
                    refs.extend(find_refs(v))
        elif isinstance(obj, list):
            for item in obj:
                refs.extend(find_refs(item))
        return refs
        
    print(f"References found: {find_refs(raw_schema)}")

    # 2. Sanitized Vertex Schema
    try:
        vertex_schema = _prepare_vertex_schema(model_class)
        print("Vertex Schema Generation: SUCCESS")
        print(json.dumps(vertex_schema, indent=2))
        
        # Verify no $ref remains
        remaining_refs = find_refs(vertex_schema)
        if remaining_refs:
            print(f"FAILED: Remaining $refs found: {remaining_refs}")
        else:
            print("SUCCESS: No $refs remaining.")
            
        # Verify no 'definitions' or '$defs'
        if 'definitions' in vertex_schema or '$defs' in vertex_schema:
             print("FAILED: definitions/$defs still present at root.")
             
    except Exception as e:
        print(f"Vertex Schema Generation FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_schema_generation(FlashcardModel)
