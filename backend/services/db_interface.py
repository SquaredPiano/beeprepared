import os
import httpx
from typing import Optional, Any, Dict, List
from uuid import UUID
from backend.models.protocol import JobBundle
from backend.models.jobs import JobModel

class DBInterface:
    def __init__(self):
        self.url = os.environ.get("SUPABASE_URL")
        self.key = os.environ.get("SUPABASE_KEY")
        if not self.url or not self.key:
            raise ValueError("Missing SUPABASE credentials")
        
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self.rest_url = f"{self.url}/rest/v1"

    def _rpc(self, function_name: str, params: Dict[str, Any]) -> Any:
        url = f"{self.rest_url}/rpc/{function_name}"
        resp = httpx.post(url, headers=self.headers, json=params)
        resp.raise_for_status()
        
        # Handle 204 No Content (common for void-returning RPCs like commit_job_bundle)
        if resp.status_code == 204 or not resp.content:
            return None
        
        return resp.json()

    def claim_job(self) -> Optional[JobModel]:
        """
        Calls the claim_next_job RPC.
        Returns a JobModel or None if queue is empty.
        """
        try:
            data = self._rpc("claim_next_job", {})
            if not data:
                return None
            
            job_data = data[0]
            model_data = {
                "id": job_data['j_id'],
                "project_id": job_data['j_project_id'],
                "type": job_data['j_type'],
                "status": job_data['j_status'],
                "payload": job_data['j_payload'],
                "result": job_data['j_result'] or {},
                "created_at": job_data['j_created_at'],
                "started_at": job_data['j_started_at'],
                "completed_at": job_data['j_completed_at'],
                "error_message": job_data['j_error_message']
            }
            return JobModel(**model_data)
        except Exception as e:
            # If 404/500, log it.
            print(f"DB Claim Error: {e}")
            return None

    def commit_bundle(self, bundle: JobBundle) -> None:
        """
        Calls commit_job_bundle RPC.
        """
        # Serialize UUIDs
        clean_artifacts = [
            {k: (str(v) if isinstance(v, UUID) else v) for k,v in a.model_dump().items()} 
            for a in bundle.artifacts
        ]
        clean_edges = [
            {k: (str(v) if isinstance(v, UUID) else v) for k,v in e.model_dump().items()} 
            for e in bundle.edges
        ]
        clean_renderings = [
            {k: (str(v) if isinstance(v, UUID) else v) for k,v in r.model_dump().items()} 
            for r in bundle.renderings
        ]

        rpc_args = {
            "_job_id": str(bundle.job_id),
            "_project_id": str(bundle.project_id),
            "_artifacts": clean_artifacts,
            "_edges": clean_edges,
            "_renderings": clean_renderings,
            "_result": bundle.result
        }

        try:
            self._rpc("commit_job_bundle", rpc_args)
        except Exception as e:
            print(f"CRITICAL: Commit Bundle Failed for Job {bundle.job_id}: {e}")
            raise e

    def fail_job(self, job_id: UUID, error_message: str) -> None:
        """
        Marks a job as FAILED via PATCH to /jobs.
        """
        url = f"{self.rest_url}/jobs?id=eq.{str(job_id)}"
        update_data = {
            "status": "failed", 
            "error_message": error_message,
        }
        try:
            httpx.patch(url, headers=self.headers, json=update_data)
        except Exception as e:
            print(f"CRITICAL: Failed to mark job {job_id} as FAILED: {e}")

    def get_artifact(self, artifact_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Fetches a single artifact by ID.
        """
        url = f"{self.rest_url}/artifacts?id=eq.{str(artifact_id)}"
        try:
            resp = httpx.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            if data and len(data) > 0:
                return data[0]
            return None
        except Exception as e:
            print(f"DB Error fetching artifact {artifact_id}: {e}")
            raise e

    def get_parent_edge(self, child_artifact_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Fetches the first parent edge for a given child artifact.
        For multi-parent lookups, use get_all_parent_edges.
        """
        url = f"{self.rest_url}/artifact_edges?child_artifact_id=eq.{str(child_artifact_id)}"
        try:
            resp = httpx.get(url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            if data and len(data) > 0:
                return data[0]
            return None
        except Exception as e:
            print(f"DB Error fetching parent edge for {child_artifact_id}: {e}")
            raise e

    def get_all_parent_edges(self, child_artifact_id: UUID) -> List[Dict[str, Any]]:
        """
        Fetches ALL parent edges for a given child artifact.
        Supports multi-parent DAG where one artifact derives from multiple sources.
        """
        url = f"{self.rest_url}/artifact_edges?child_artifact_id=eq.{str(child_artifact_id)}"
        try:
            resp = httpx.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json() or []
        except Exception as e:
            print(f"DB Error fetching parent edges for {child_artifact_id}: {e}")
            raise e


