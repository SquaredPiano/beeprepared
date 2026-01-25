#!/usr/bin/env python3
"""Debug script to inspect job results."""

import json
import urllib.request

def main():
    url = "http://localhost:8000/api/jobs"
    
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        print(f"Error fetching jobs: {e}")
        return
    
    jobs = data if isinstance(data, list) else data.get('jobs', [])
    print(f"Total jobs: {len(jobs)}")
    print()
    
    # Show last 10 completed jobs
    completed = [j for j in jobs if j.get('status') == 'completed']
    print(f"Completed jobs: {len(completed)}")
    print()
    
    for j in completed[-10:]:
        result = j.get('result', {})
        print(f"Job {j['id'][:8]}... type={j.get('type'):12}")
        print(f"  result: {json.dumps(result)[:100]}")
        print()

if __name__ == "__main__":
    main()
