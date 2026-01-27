/**
 * Job API Client
 * 
 * Transport layer for communicating with the BeePrepared backend.
 * This is the ONLY way the frontend should interact with job processing.
 * 
 * API Contract: See /API_CONTRACT.md
 */

const API_BASE = 'http://localhost:8000';

// ============================================================================
// Types
// ============================================================================

export interface JobResponse {
    job_id: string;
}

export interface JobStatus {
    id: string;
    project_id: string;
    type: 'ingest' | 'generate';
    status: 'pending' | 'running' | 'completed' | 'failed';
    payload: Record<string, any>;
    result?: {
        status: string;
        source_artifact_id?: string;
        core_artifact_id?: string;
        artifact_id?: string;
        artifact_type?: string;
    };
    error_message?: string;
}

export interface Artifact {
    id: string;
    project_id: string;
    type: string;
    content: Record<string, any>;
    created_at: string;
}

export interface Edge {
    id: string;
    parent_artifact_id: string;
    child_artifact_id: string;
    relationship_type: string;
}

export interface ProjectArtifacts {
    artifacts: Artifact[];
    edges: Edge[];
}

export interface IngestPayload {
    source_type: 'youtube' | 'audio' | 'video' | 'pdf' | 'pptx' | 'md';
    source_ref: string;
    original_name: string;
}

export interface GeneratePayload {
    source_artifact_id: string;
    target_type: 'quiz' | 'exam' | 'notes' | 'slides' | 'flashcards';
}

// ============================================================================
// API Functions
// ============================================================================

/**
 * Create a new job (ingest or generate)
 */
export async function createJob(
    projectId: string,
    type: 'ingest' | 'generate',
    payload: IngestPayload | GeneratePayload
): Promise<string> {
    const response = await fetch(`${API_BASE}/api/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            project_id: projectId,
            type,
            payload,
        }),
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `Failed to create job: ${response.status}`);
    }

    const data: JobResponse = await response.json();
    return data.job_id;
}

/**
 * Get job status
 */
export async function getJobStatus(jobId: string): Promise<JobStatus> {
    const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `Failed to get job: ${response.status}`);
    }

    return response.json();
}

/**
 * Poll job until completion (or failure)
 * 
 * @param jobId - Job ID to poll
 * @param intervalMs - Polling interval in milliseconds (default: 2000)
 * @param timeoutMs - Maximum time to wait (default: 300000 = 5 min)
 */
export async function pollJobUntilComplete(
    jobId: string,
    intervalMs = 2000,
    timeoutMs = 300000
): Promise<JobStatus> {
    const startTime = Date.now();

    while (Date.now() - startTime < timeoutMs) {
        const status = await getJobStatus(jobId);

        if (status.status === 'completed') {
            return status;
        }

        if (status.status === 'failed') {
            throw new Error(`Job failed: ${status.error_message}`);
        }

        // Wait before next poll
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }

    throw new Error(`Job timed out after ${timeoutMs}ms`);
}

/**
 * Fetch all artifacts for a project
 */
export async function fetchProjectArtifacts(projectId: string): Promise<ProjectArtifacts> {
    const response = await fetch(`${API_BASE}/api/projects/${projectId}/artifacts`);

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || `Failed to fetch artifacts: ${response.status}`);
    }

    return response.json();
}

// ============================================================================
// Convenience Wrappers
// ============================================================================

/**
 * Ingest a source and wait for completion
 */
export async function ingestSource(
    projectId: string,
    sourceType: IngestPayload['source_type'],
    sourceRef: string,
    originalName: string
): Promise<JobStatus> {
    const jobId = await createJob(projectId, 'ingest', {
        source_type: sourceType,
        source_ref: sourceRef,
        original_name: originalName,
    });

    console.log(`[JobAPI] Created ingest job: ${jobId}`);
    return pollJobUntilComplete(jobId);
}

/**
 * Generate an artifact from a knowledge core
 */
export async function generateArtifact(
    projectId: string,
    sourceArtifactId: string,
    targetType: GeneratePayload['target_type']
): Promise<JobStatus> {
    const jobId = await createJob(projectId, 'generate', {
        source_artifact_id: sourceArtifactId,
        target_type: targetType,
    });

    console.log(`[JobAPI] Created generate job: ${jobId}`);
    return pollJobUntilComplete(jobId);
}
