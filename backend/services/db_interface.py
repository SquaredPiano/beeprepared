import os
from typing import Optional, Any, Dict
from uuid import UUID
from supabase import create_client, Client
from backend.models.protocol import JobBundle
# Use the existing JobModel for return type of claim_job
from backend.models.jobs import JobModel

class DBInterface:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise ValueError("Missing SUPABASE credentials")
        self.supabase: Client = create_client(url, key)

    def claim_job(self) -> Optional[JobModel]:
        """
        Calls the claim_next_job RPC.
        Returns a JobModel or None if queue is empty.
        """
        try:
            response = self.supabase.rpc("claim_next_job", {}).execute()
            if not response.data:
                return None
            
            job_data = response.data[0]
            # Map RPC returns (j_ prefix) to model
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
            # Determine if this should be silent or loud. 
            # Network errors -> loud? Empty queue -> handles in logic.
            # strict logic: if claim fails due to DB error, we should probably log and return None 
            # or raise. Let's raise to be safe, runner loop can handle sleep.
            print(f"DB Claim Error: {e}")
            raise e

    def commit_bundle(self, bundle: JobBundle) -> None:
        """
        Calls commit_job_bundle RPC.
        Raises exception on ANY failure.
        """
        payload = {
            "_job_id": str(bundle.job_id),
            "_project_id": str(bundle.project_id),
            "_artifacts": [a.model_dump() for a in bundle.artifacts],
            "_edges": [e.model_dump() for e in bundle.edges],
            "_renderings": [r.model_dump() for r in bundle.renderings],
            "_result": bundle.result
        }
        
        # Serialize UUIDs to strings in the list comprehensions? 
        # Pydantic model_dump(mode='json') handles UUIDs usually, but supabase-py might expect dicts with strings.
        # Let's ensure serialization.
        
        # Helper to strict serialize
        import json
        from backend.models.protocol import ArtifactPayload
        
        # Actually pydantic's model_dump(mode='json') is safer for UUIDs
        # But we need to pass a dict to supabase-py which then JSON dumps it.
        # So we want python dicts where UUIDs are STRINGS.
        
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
            self.supabase.rpc("commit_job_bundle", rpc_args).execute()
        except Exception as e:
            print(f"CRITICAL: Commit Bundle Failed for Job {bundle.job_id}: {e}")
            raise e

    def fail_job(self, job_id: UUID, error_message: str) -> None:
        """
        Marks a job as FAILED.
        """
        try:
            self.supabase.table("jobs").update({
                "status": "failed", 
                "error_message": error_message,
                "completed_at": "now()" # Let DB handle time or passthrough? DB trigger update_modtime handles updated_at, but we need completed_at.
                # Actually schema says completed_at is timestamp.
            }).eq("id", str(job_id)).execute()
        except Exception as e:
            print(f"CRITICAL: Failed to mark job {job_id} as FAILED: {e}")
            # Nothing more we can do if DB is down.

    def get_artifact(self, artifact_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Fetches a single artifact by ID.
        
        Returns the artifact row as a dict, or None if not found.
        """
        try:
            response = self.supabase.table("artifacts").select("*").eq("id", str(artifact_id)).execute()
            if response.data and len(response.data) > 0:
                return response.data[0]
            return None
        except Exception as e:
            print(f"DB Error fetching artifact {artifact_id}: {e}")
            raise e

