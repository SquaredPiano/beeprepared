import { supabase } from "./supabase";

// Backend API base URL
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

export interface Project {
  id: string;
  name: string;
  description?: string;
  user_id: string;
  canvas_state?: {
    viewport: { x: number; y: number; zoom: number };
    node_positions: Record<string, { x: number; y: number }>;
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
      const { data, error } = await supabase
        .from("projects")
        .select("*")
        .order("updated_at", { ascending: false });
      if (error) throw error;
      return data as Project[];
    },

    async get(id: string): Promise<Project> {
      const { data, error } = await supabase
        .from("projects")
        .select("*")
        .eq("id", id)
        .single();
      if (error) throw error;
      return data as Project;
    },

    async create(name: string, description?: string): Promise<Project> {
      const { data: userData } = await supabase.auth.getUser();
      const { data, error } = await supabase
        .from("projects")
        .insert({
          name,
          description,
          user_id: userData.user?.id,
          canvas_state: {
            viewport: { x: 0, y: 0, zoom: 1 },
            node_positions: {}
          }
        })
        .select()
        .single();
      if (error) throw error;
      return data as Project;
    },

    async update(id: string, updates: Partial<Pick<Project, "name" | "description" | "canvas_state">>): Promise<Project> {
      const { data, error } = await supabase
        .from("projects")
        .update(updates)
        .eq("id", id)
        .select()
        .single();
      if (error) throw error;
      return data as Project;
    },

    async delete(id: string): Promise<void> {
      const { error } = await supabase
        .from("projects")
        .delete()
        .eq("id", id);
      if (error) throw error;
    },

    async getArtifacts(projectId: string): Promise<{ artifacts: Artifact[]; edges: ArtifactEdge[] }> {
      // Use the backend API to get artifacts and edges
      const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/artifacts`);
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Failed to fetch artifacts" }));
        throw new Error(err.detail || "Failed to fetch artifacts");
      }
      return response.json();
    }
  },

  jobs: {
    async create(projectId: string, type: "ingest" | "generate", payload: any): Promise<{ job_id: string }> {
      const response = await fetch(`${BACKEND_URL}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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
      const response = await fetch(`${BACKEND_URL}/api/jobs/${jobId}`);
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
      onProgress?: (job: Job) => void
    ): Promise<{ job_id: string; job: Job }> {
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
      
      // Upload and create ingest job
      const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/upload`, {
        method: "POST",
        body: formData
      });
      
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: "Upload failed" }));
        throw new Error(err.detail || "Upload failed");
      }
      
      const { job_id } = await response.json();
      
      // Poll for completion
      const job = await api.jobs.poll(job_id, onProgress || (() => {}));
      
      return { job_id, job };
    }
  },

  points: {
    async getBalance(): Promise<number> {
      const { data: userData } = await supabase.auth.getUser();
      if (!userData.user) return 0;
      
      const { data, error } = await supabase
        .from("honey_points")
        .select("amount")
        .eq("user_id", userData.user.id);
      
      if (error) {
        // Table might not exist yet, return 0
        console.warn("Could not fetch honey points:", error.message);
        return 0;
      }
      
      return data.reduce((sum, entry) => sum + entry.amount, 0);
    }
  }
};
