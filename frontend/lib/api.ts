import { getAccessToken } from "./auth";

// Backend API base URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export interface Project {
  id: string;
  name: string;
  description?: string;
  user_id: string;
  canvas_state?: {
    viewport: { x: number; y: number; zoom: number };
    nodes: any[];
    edges: any[];
  };

  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: string;
  project_id: string;
  type: "video" | "audio" | "text" | "flat_text" | "knowledge_core" | "quiz" | "flashcards" | "notes" | "slides" | "exam";
  content: any;
  created_at: string;
  created_by_job_id?: string;
}

export interface ArtifactEdge {
  id: string;
  project_id: string;
  parent_artifact_id: string;
  child_artifact_id: string;
  relationship_type: "derived_from" | "contains" | "references";
  created_at: string;
}

export interface Job {
  id: string;
  project_id: string;
  type: "ingest" | "extract" | "clean" | "generate" | "render";
  status: "pending" | "running" | "completed" | "failed";
  payload: any;
  result?: any;
  error_message?: string;
  created_at: string;
}

export const api = {
  projects: {
    async list(): Promise<Project[]> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/projects`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!response.ok) throw new Error("Failed to fetch projects");
      return response.json();
    },

    async get(id: string): Promise<Project> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/projects/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!response.ok) throw new Error("Failed to fetch project");
      return response.json();
    },


    async create(name: string, description?: string): Promise<Project> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/projects`, {
        method: "POST",
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name, description })
      });
      if (!response.ok) throw new Error("Creation failed");
      return response.json();
    },


    async update(id: string, updates: Partial<Pick<Project, "name" | "description" | "canvas_state">>): Promise<Project> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/projects/${id}`, {
        method: "PATCH",
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(updates)
      });
      if (!response.ok) throw new Error("Update failed");
      return response.json();
    },

    async delete(id: string): Promise<void> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/projects/${id}`, {
        method: "DELETE",
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!response.ok) throw new Error("Delete failed");
    },

    async getArtifacts(projectId: string): Promise<{ artifacts: Artifact[]; edges: ArtifactEdge[] }> {
      const token = await getAccessToken();

      // Use the backend API to get artifacts and edges
      // Note: If projectId is a mock ID (e.g. proj-1), backend might 404. 
      // User says "backend works", implying maybe we should try real fetch.
      try {
        const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/artifacts`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!response.ok) {
          // If backend fails (e.g. project not found), return empty for demo to avoid crashing
          console.warn("Backend getArtifacts failed, returning empty for demo", response.status);
          return { artifacts: [], edges: [] };
        }
        return response.json();
      } catch (err) {
        console.warn("Backend getArtifacts error", err);
        return { artifacts: [], edges: [] };
      }
    }
  },

  vault: {
    async list(path: string = "/"): Promise<{ files: Artifact[] }> {
      const token = await getAccessToken();

      const response = await fetch(`${BACKEND_URL}/api/vault?path=${encodeURIComponent(path)}`, {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });
      if (!response.ok) {
        throw new Error("Failed to load vault");
      }
      return response.json();
    }
  },

  artifacts: {
    async update(id: string, updates: { content?: any; markdown?: string }): Promise<Artifact> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/artifacts/${id}`, {
        method: "PATCH",
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(updates)
      });
      if (!response.ok) throw new Error("Failed to update artifact");
      return response.json();
    }
  },

  jobs: {
    async list(projectId?: string): Promise<Job[]> {
      const token = await getAccessToken();
      const url = projectId
        ? `${BACKEND_URL}/api/jobs?project_id=${projectId}`
        : `${BACKEND_URL}/api/jobs`;

      const response = await fetch(url, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      // Handle 403 gracefully - project may have been deleted
      if (response.status === 403) {
        console.warn("[api.jobs.list] Access denied - project may be deleted");
        return [];
      }
      if (!response.ok) {
        throw new Error("Failed to fetch jobs");
      }
      return response.json();
    },

    async create(projectId: string, type: "ingest" | "generate", payload: any): Promise<{ job_id: string }> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/jobs`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          project_id: projectId,
          type,
          payload
        })
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Failed to create job" }));
        throw new Error(err.detail || "Failed to create job");
      }
      return response.json();
    },

    async getStatus(jobId: string): Promise<Job> {
      const token = await getAccessToken();
      const response = await fetch(`${BACKEND_URL}/api/jobs/${jobId}`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Failed to get job status" }));
        throw new Error(err.detail || "Failed to get job status");
      }
      return response.json();
    },

    async poll(jobId: string, onUpdate: (job: Job) => void, intervalMs = 1000): Promise<Job> {
      return new Promise((resolve, reject) => {
        const check = async () => {
          try {
            const job = await this.getStatus(jobId);
            onUpdate(job);

            if (job.status === "completed") {
              resolve(job);
            } else if (job.status === "failed") {
              reject(new Error(job.error_message || "Job failed"));
            } else {
              setTimeout(check, intervalMs);
            }
          } catch (error) {
            reject(error);
          }
        };
        check();
      });
    }
  },

  upload: {
    async uploadAndIngest(
      projectId: string,
      file: File,
      folder: string = "/",
      onProgress?: (job: Job) => void
    ): Promise<{ job_id: string; job: Job }> {
      const token = await getAccessToken();

      // Determine source type from file
      const ext = file.name.split(".").pop()?.toLowerCase() || "";
      let sourceType: string;

      if (["mp3", "wav", "m4a", "ogg", "flac"].includes(ext)) {
        sourceType = "audio";
      } else if (["mp4", "mov", "avi", "webm", "mkv"].includes(ext)) {
        sourceType = "video";
      } else if (ext === "pdf") {
        sourceType = "pdf";
      } else if (ext === "pptx") {
        sourceType = "pptx";
      } else if (["md", "txt"].includes(ext)) {
        sourceType = "md";
      } else {
        throw new Error(`Unsupported file type: ${ext}`);
      }

      // Create form data
      const formData = new FormData();
      formData.append("file", file);
      formData.append("source_type", sourceType);
      formData.append("folder", folder);

      // Upload and create ingest job (include auth token)
      const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/upload`, {
        method: "POST",
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail || "Upload failed");
      }

      const { job_id } = await response.json();

      // Return immediately so UI can use Realtime to track progress
      // The backend creates the job in 'pending' state
      const job: Job = {
        id: job_id,
        project_id: projectId,
        type: "ingest",
        status: "pending",
        payload: { source_type: sourceType },
        created_at: new Date().toISOString()
      };

      return { job_id, job };
    }
  },

  points: {
    async getBalance(): Promise<number> {
      // Mock implementation for demo mode
      return 100; // Return mock points balance
    }
  }
};
