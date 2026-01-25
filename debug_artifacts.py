#!/usr/bin/env python3
"""Debug script to inspect artifact structure from the API."""

import json
import urllib.request

def main():
    url = "http://localhost:8000/api/projects/00000000-0000-0000-0000-000000000001/artifacts"
    
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"Error fetching artifacts: {e}")
        return
    
    artifacts = data.get('artifacts', [])
    print(f"Total artifacts: {len(artifacts)}")
    print()
    
    # Find one of each type to inspect structure
    seen_types = set()
    for a in reversed(artifacts):
        atype = a.get('type')
        if atype in seen_types:
            continue
        seen_types.add(atype)
        
        content = a.get('content', {})
        data_obj = content.get('data', {})
        core_obj = content.get('core', {})
        
        print(f"TYPE: {atype}")
        print(f"  id: {a['id']}")
        print(f"  content.kind: {content.get('kind')}")
        
        if data_obj:
            print(f"  content.data keys: {list(data_obj.keys())}")
            if 'questions' in data_obj:
                print(f"    questions count: {len(data_obj['questions'])}")
            if 'sections' in data_obj:
                print(f"    sections count: {len(data_obj['sections'])}")
            if 'cards' in data_obj:
                print(f"    cards count: {len(data_obj['cards'])}")
            if 'slides' in data_obj:
                print(f"    slides count: {len(data_obj['slides'])}")
        
        # Check for binary
        binary = content.get('binary', {})
        if binary:
            print(f"  content.binary: format={binary.get('format')}, path={binary.get('storage_path')}")
        else:
            print(f"  content.binary: NONE")
        
        if core_obj:
            print(f"  content.core keys: {list(core_obj.keys())}")
        
        print()

if __name__ == "__main__":
    main()
