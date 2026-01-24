import json
import glob
import re

def audit_file(filepath):
    print(f"\n--- Auditing {filepath} ---")
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        # Recursive search for strings
        def check_latex(obj, path=""):
            if isinstance(obj, str):
                # Check for suspicious patterns
                # 1. "frac" without backslash
                if re.search(r'(?<!\\)frac\{', obj):
                    print(f"[POTENTIAL ERROR] Found 'frac{{' without backslash at {path}: {obj[:50]}...")
                # 2. LaTeX-like chars without delimiters
                if re.search(r'\\[a-zA-Z]+', obj) and not ('$' in obj):
                    # It might be normal text with newline \n, so be careful.
                    # ignore \n, \t, \", \'
                    if re.search(r'\\[^nt"\'\\]', obj):
                         print(f"[WARNING] Found LaTeX-like command without $ delimiters at {path}: {obj}")
                # 3. Double-escaped backslashes count
                # We expect '\\frac' in the file string means '\frac' in memory.
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    check_latex(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    check_latex(v, f"{path}[{i}]")
                    
        check_latex(data)
    except Exception as e:
        print(f"Failed to read {filepath}: {e}")

files = glob.glob("output/*.json")
for f in files:
    audit_file(f)
