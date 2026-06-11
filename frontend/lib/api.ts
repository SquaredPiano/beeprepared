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

/** Artifact types the backend can generate. Mirrors GENERATED_ARTIFACT_TYPES. */
export const GENERATED_TYPES = [
  "notes",
  "quiz",
  "flashcards",
  "slides",
  "exam",
  "study_guide",
  "cheatsheet",
  "mindmap",
] as const;

export type GeneratedType = (typeof GENERATED_TYPES)[number];

export type ArtifactType =
  | "video"
  | "audio"
  | "pdf"
  | "pptx"
  | "md"
  | "youtube"
  | "text"
  | "flat_text"
  | "knowledge_core"
  | GeneratedType;

export interface Artifact {
  id: string;
  project_id: string;
  type: ArtifactType;
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
  type: "ingest" | "generate" | "refine";
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  payload: any;
  result?: any;
  error_message?: string;
  created_at: string;
  attempts?: number;
}

/** One generator node in a compiled flow plan. */
export interface FlowStep {
  node_id: string;
  target_type: GeneratedType;
  parents: string[];
  depth: number;
}

export interface FlowPlan {
  valid: boolean;
  steps: FlowStep[];
  waves: number;
  error?: string;
}

export type FlowNodeStatus =
  | "pending"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export interface FlowNodeState {
  status: FlowNodeStatus;
  job_id?: string;
  artifact_id?: string;
  error?: string;
  target_type?: GeneratedType;
  source_artifact_ids?: string[];
}

export interface FlowRun {
  id: string;
  project_id: string;
  status: "running" | "completed" | "failed";
  node_states: Record<string, FlowNodeState>;
  plan: { steps: FlowStep[]; seed_artifacts: Record<string, string> };
  result?: { completed: number; failed: number; skipped: number };
  created_at?: string;
  completed_at?: string;
}

export interface ChatReply {
  reply: string;
  action: "answer" | "refine" | "generate";
  job_id?: string;
  target_type?: GeneratedType;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  artifact_id?: string;
  metadata?: { action?: string; job_id?: string };
  created_at: string;
}

/** What this backend deployment supports. Drives the node palette. */
export interface Capabilities {
  artifact_types: GeneratedType[];
  source_types: string[];
  features: {
    flows: boolean;
    refine: boolean;
    assistant: boolean;
    realtime: boolean;
    offline_llm: boolean;
  };
}

/** Raise the API's error detail instead of a generic "request failed". */
async function failure(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(body?.detail || body?.error || `${fallback} (HTTP ${response.status})`);
}

async function authorized(extra: Record<string, string> = {}): Promise<HeadersInit> {
  const token = await getAccessToken();
  return { Authorization: `Bearer ${token}`, ...extra };
}

const JSON_HEADERS = { "Content-Type": "application/json" };

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
    async get(id: string): Promise<Artifact> {
      const response = await fetch(`${BACKEND_URL}/api/artifacts/${id}`, {
        headers: await authorized(),
      });
      if (!response.ok) throw await failure(response, "Could not load the artifact");
      return response.json();
    },

    /**
     * Provenance: which artifacts this was built from, and what was built on it.
     * Both sides are lists - an artifact generated from several sources has
     * several parents.
     */
    async lineage(id: string): Promise<{ artifact: Artifact; parents: Artifact[]; children: Artifact[] }> {
      const response = await fetch(`${BACKEND_URL}/api/artifacts/${id}/lineage`, {
        headers: await authorized(),
      });
      if (!response.ok) throw await failure(response, "Could not load lineage");
      return response.json();
    },

    /** A time-limited URL for the artifact's rendered file (PDF, PPTX, Markdown). */
    async downloadUrl(
      id: string,
      inline = false,
    ): Promise<{ download_url: string; format: string; mime_type: string; filename: string }> {
      const response = await fetch(
        `${BACKEND_URL}/api/artifacts/${id}/download?inline=${inline}`,
        { headers: await authorized() },
      );
      if (!response.ok) throw await failure(response, "No download is available for this artifact");
      const body = await response.json();
      // Local storage returns a relative path; make it absolute for the browser.
      if (body.download_url.startsWith("/")) {
        body.download_url = `${BACKEND_URL}${body.download_url}`;
      }
      return body;
    },

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
      if (!response.ok) {
        const errText = await response.text();
        console.error("Artifact update failed:", response.status, errText);
        throw new Error(`Failed to update artifact: ${errText}`);
      }
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

    /** Stop a queued or running job. */
    async cancel(jobId: string): Promise<void> {
      const response = await fetch(`${BACKEND_URL}/api/jobs/${jobId}/cancel`, {
        method: "POST",
        headers: await authorized(),
      });
      if (!response.ok) throw await failure(response, "Could not cancel the job");
    },

    async create(
      projectId: string,
      type: "ingest" | "generate" | "refine",
      payload: any,
    ): Promise<{ job_id: string; reused?: boolean }> {
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

  /**
   * Flow execution: run the canvas as a dependency graph.
   *
   * `validate` is side-effect free and is what the canvas calls while you wire
   * nodes together; `run` compiles the same graph and starts executing it.
   */
  flows: {
    async validate(projectId: string, nodes: any[], edges: any[]): Promise<FlowPlan> {
      const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/flow/validate`, {
        method: "POST",
        headers: await authorized(JSON_HEADERS),
        body: JSON.stringify({ nodes, edges }),
      });
      if (!response.ok) throw await failure(response, "Could not validate the flow");
      return response.json();
    },

    async run(projectId: string, nodes: any[], edges: any[]): Promise<FlowRun> {
      const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/flow/run`, {
        method: "POST",
        headers: await authorized(JSON_HEADERS),
        body: JSON.stringify({ nodes, edges }),
      });
      if (!response.ok) throw await failure(response, "Could not start the flow");
      return response.json();
    },

    async get(projectId: string, flowRunId: string): Promise<FlowRun> {
      const response = await fetch(
        `${BACKEND_URL}/api/projects/${projectId}/flow/runs/${flowRunId}`,
        { headers: await authorized() },
      );
      if (!response.ok) throw await failure(response, "Could not load the flow run");
      return response.json();
    },

    async list(projectId: string): Promise<FlowRun[]> {
      const response = await fetch(`${BACKEND_URL}/api/projects/${projectId}/flow/runs`, {
        headers: await authorized(),
      });
      if (!response.ok) throw await failure(response, "Could not list flow runs");
      return response.json();
    },
  },

  /** The assistant panel: ask a question, or ask for the artifact to change. */
  chat: {
    async send(projectId: string, message: string, artifactId?: string): Promise<ChatReply> {
      const response = await fetch(`${BACKEND_URL}/api/chat`, {
        method: "POST",
        headers: await authorized(JSON_HEADERS),
        body: JSON.stringify({ project_id: projectId, message, artifact_id: artifactId }),
      });
      if (!response.ok) throw await failure(response, "The assistant did not respond");
      return response.json();
    },

    async history(projectId: string): Promise<ChatMessage[]> {
      const response = await fetch(`${BACKEND_URL}/api/chat/${projectId}/history`, {
        headers: await authorized(),
      });
      if (!response.ok) return [];
      return response.json();
    },
  },

  async capabilities(): Promise<Capabilities> {
    const response = await fetch(`${BACKEND_URL}/api/capabilities`);
    if (!response.ok) throw await failure(response, "Could not read backend capabilities");
    return response.json();
  },

  points: {
    /** Gamification placeholder. Not yet backed by the API. */
    async getBalance(): Promise<number> {
      return 100;
    },
  },
};
