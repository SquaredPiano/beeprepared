#!/usr/bin/env python3
"""
🐝 BeePrepared User Flow Test Suite
Simulates real user actions through the system to verify integration.

This script tests:
1. Project creation
2. File upload to R2/storage
3. Ingest job creation and processing
4. Artifact creation verification
5. Pipeline end-to-end flow
"""

import os
import sys
import json
import uuid
import time
import tempfile
import requests
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Test configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Bee-themed test output
def bee_print(msg: str, emoji: str = "🐝"):
    print(f"{emoji} {msg}")

def success(msg: str):
    bee_print(msg, "✅")

def error(msg: str):
    bee_print(msg, "❌")

def info(msg: str):
    bee_print(msg, "🍯")

def divider(title: str):
    print(f"\n{'='*50}")
    print(f"🐝 {title}")
    print('='*50)


class BeeTestSuite:
    """Simulates user actions to test the BeePrepared system."""
    
    def __init__(self):
        self.backend_url = BACKEND_URL
        self.project_id: Optional[str] = None
        self.job_ids: list[str] = []
        self.artifact_ids: list[str] = []
        
    def check_backend_health(self) -> bool:
        """Check if backend is running."""
        divider("Backend Health Check")
        try:
            response = requests.get(f"{self.backend_url}/health", timeout=5)
            if response.status_code == 200:
                success(f"Backend is healthy at {self.backend_url}")
                return True
            else:
                error(f"Backend returned status {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            error(f"Cannot connect to backend at {self.backend_url}")
            info("Make sure to run: uvicorn backend.api:app --reload")
            return False
    
    def create_project(self, name: str = "Test Hive") -> bool:
        """Simulate user creating a new project."""
        divider("Create New Project (Hive)")
        try:
            response = requests.post(
                f"{self.backend_url}/api/projects",
                json={"name": name, "description": "Automated test hive"},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.project_id = data.get("id")
                success(f"Created project: {name} (ID: {self.project_id})")
                return True
            else:
                error(f"Failed to create project: {response.status_code}")
                info(f"Response: {response.text}")
                return False
        except Exception as e:
            error(f"Error creating project: {e}")
            return False
    
    def upload_test_file(self) -> bool:
        """Create and upload a test file."""
        divider("Upload Test File")
        
        if not self.project_id:
            error("No project ID - create project first")
            return False
        
        # Create a test markdown file
        test_content = """# BeePrepared Test Document
        
## Introduction to Knowledge Extraction

This is a test document designed to verify the bee agent pipeline.

### Key Concepts

1. **Ingestion**: The process of taking raw input and preparing it for processing.
2. **Extraction**: Pulling structured information from unstructured content.
3. **Knowledge Core**: The central repository of extracted knowledge.
4. **Generation**: Creating study materials from the knowledge core.

### Sample Quiz Questions

Q1: What is the first step in the BeePrepared pipeline?
A: Ingestion

Q2: What is the central repository called?
A: Knowledge Core

### Summary

The bee agents work together to transform educational materials into
high-quality study resources. Each agent has a specific role:

- **Ingest Worker**: Handles initial file processing
- **Extract Worker**: Pulls out key information
- **Clean Worker**: Ensures data quality
- **Generate Worker**: Creates study materials
- **Render Worker**: Formats final output

Together, they form the BeePrepared hive mind.
"""
        
        # Create temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(test_content)
            temp_path = f.name
        
        try:
            with open(temp_path, 'rb') as f:
                files = {'file': ('test_document.md', f, 'text/markdown')}
                data = {'source_type': 'md'}
                
                response = requests.post(
                    f"{self.backend_url}/api/projects/{self.project_id}/upload",
                    files=files,
                    data=data
                )
            
            if response.status_code == 200:
                result = response.json()
                job_id = result.get("job_id")
                self.job_ids.append(job_id)
                success(f"File uploaded, job created: {job_id}")
                return True
            else:
                error(f"Upload failed: {response.status_code}")
                info(f"Response: {response.text}")
                return False
                
        except Exception as e:
            error(f"Error uploading file: {e}")
            return False
        finally:
            os.unlink(temp_path)
    
    def poll_job_completion(self, job_id: str, timeout: int = 60) -> bool:
        """Poll a job until completion or timeout."""
        divider(f"Polling Job: {job_id[:8]}...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(f"{self.backend_url}/api/jobs/{job_id}")
                if response.status_code == 200:
                    job = response.json()
                    status = job.get("status", "unknown")
                    
                    if status == "completed":
                        success(f"Job completed successfully")
                        return True
                    elif status == "failed":
                        error(f"Job failed: {job.get('error_message', 'Unknown error')}")
                        return False
                    else:
                        info(f"Job status: {status}...")
                        time.sleep(2)
                else:
                    error(f"Failed to get job status: {response.status_code}")
                    return False
            except Exception as e:
                error(f"Error polling job: {e}")
                return False
        
        error(f"Job timed out after {timeout}s")
        return False
    
    def check_artifacts(self) -> bool:
        """Verify artifacts were created."""
        divider("Checking Artifacts")
        
        if not self.project_id:
            error("No project ID")
            return False
        
        try:
            response = requests.get(
                f"{self.backend_url}/api/projects/{self.project_id}/artifacts"
            )
            
            if response.status_code == 200:
                data = response.json()
                artifacts = data.get("artifacts", [])
                edges = data.get("edges", [])
                
                if artifacts:
                    success(f"Found {len(artifacts)} artifacts")
                    for art in artifacts:
                        info(f"  - {art['type']}: {art['id'][:8]}...")
                        self.artifact_ids.append(art['id'])
                    
                    if edges:
                        success(f"Found {len(edges)} edges connecting artifacts")
                    
                    return True
                else:
                    info("No artifacts found yet")
                    return False
            else:
                error(f"Failed to fetch artifacts: {response.status_code}")
                return False
                
        except Exception as e:
            error(f"Error checking artifacts: {e}")
            return False
    
    def test_generate_job(self) -> bool:
        """Test creating a generate job from knowledge core."""
        divider("Testing Generate Job")
        
        # Find knowledge_core artifact
        knowledge_core_id = None
        for art_id in self.artifact_ids:
            try:
                # We'd need to check the type, for now just try first artifact
                knowledge_core_id = art_id
                break
            except:
                pass
        
        if not knowledge_core_id:
            info("No knowledge core found, skipping generate test")
            return True
        
        try:
            response = requests.post(
                f"{self.backend_url}/api/jobs",
                json={
                    "project_id": self.project_id,
                    "type": "generate",
                    "payload": {
                        "source_artifact_id": knowledge_core_id,
                        "target_type": "quiz"
                    }
                },
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                job_id = data.get("job_id")
                success(f"Generate job created: {job_id}")
                self.job_ids.append(job_id)
                return True
            else:
                error(f"Failed to create generate job: {response.status_code}")
                return False
                
        except Exception as e:
            error(f"Error creating generate job: {e}")
            return False
    
    def cleanup(self):
        """Clean up test data."""
        divider("Cleanup")
        
        if self.project_id:
            try:
                response = requests.delete(
                    f"{self.backend_url}/api/projects/{self.project_id}"
                )
                if response.status_code in [200, 204]:
                    success(f"Deleted test project: {self.project_id[:8]}...")
                else:
                    info(f"Could not delete project: {response.status_code}")
            except:
                pass
    
    def run_full_test(self, cleanup: bool = True) -> bool:
        """Run the complete test suite."""
        print("\n" + "🐝"*25)
        print("  BEEPREPARED USER FLOW TEST SUITE")
        print("🐝"*25 + "\n")
        
        results = []
        
        # 1. Health check
        results.append(("Backend Health", self.check_backend_health()))
        if not results[-1][1]:
            error("Backend not running, stopping tests")
            return False
        
        # 2. Create project
        results.append(("Create Project", self.create_project("Test Hive Alpha")))
        
        # 3. Upload file
        results.append(("Upload File", self.upload_test_file()))
        
        # 4. Poll job if upload succeeded
        if self.job_ids:
            results.append(("Job Completion", self.poll_job_completion(self.job_ids[0])))
        
        # 5. Check artifacts
        results.append(("Artifact Check", self.check_artifacts()))
        
        # 6. Test generate (optional)
        if self.artifact_ids:
            results.append(("Generate Job", self.test_generate_job()))
        
        # Summary
        divider("Test Results Summary")
        all_passed = True
        for name, passed in results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {status}: {name}")
            if not passed:
                all_passed = False
        
        print()
        if all_passed:
            success("🎉 All tests passed! The hive is healthy!")
        else:
            error("Some tests failed. Check the output above.")
        
        # Cleanup
        if cleanup:
            self.cleanup()
        
        return all_passed


def test_frontend_api_simulation():
    """
    Simulates what the frontend API does without actually running the frontend.
    Useful for testing the integration layer.
    """
    divider("Frontend API Simulation")
    
    # This mimics what frontend/lib/api.ts does
    info("Simulating frontend API calls...")
    
    # Test 1: List projects
    try:
        response = requests.get(f"{BACKEND_URL}/api/projects")
        if response.status_code == 200:
            success(f"List projects: OK")
        elif response.status_code == 404:
            info("No /api/projects endpoint - using Supabase directly")
        else:
            error(f"List projects failed: {response.status_code}")
    except Exception as e:
        error(f"List projects error: {e}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="BeePrepared User Flow Tests")
    parser.add_argument("--no-cleanup", action="store_true", 
                        help="Don't delete test data after running")
    parser.add_argument("--backend", type=str, default=BACKEND_URL,
                        help="Backend URL to test against")
    args = parser.parse_args()
    
    BACKEND_URL = args.backend
    
    suite = BeeTestSuite()
    suite.backend_url = args.backend
    
    success = suite.run_full_test(cleanup=not args.no_cleanup)
    sys.exit(0 if success else 1)
