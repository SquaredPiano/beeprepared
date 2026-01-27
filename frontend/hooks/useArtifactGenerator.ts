'use client';

import { useState, useCallback, useRef } from 'react';
import { getAccessToken } from '@/lib/auth';
import { api, Artifact } from '@/lib/api';
import { toast } from 'sonner';

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

export type TargetType = 'quiz' | 'notes' | 'slides' | 'flashcards' | 'exam';
export type JobStatus = 'idle' | 'pending' | 'running' | 'completed' | 'failed';

export interface GenerationState {
  jobId: string | null;
  status: JobStatus;
  artifactId: string | null;
  artifact: Artifact | null;
  error: string | null;
  progress: number; // 0-100
}

const initialState: GenerationState = {
  jobId: null,
  status: 'idle',
  artifactId: null,
  artifact: null,
  error: null,
  progress: 0,
};

/**
 * Hook for generating a single artifact type from a knowledge core.
 * Handles job creation, polling, and artifact fetching.
 */
export function useArtifactGenerator() {
  const [states, setStates] = useState<Record<TargetType, GenerationState>>({
    quiz: { ...initialState },
    notes: { ...initialState },
    slides: { ...initialState },
    flashcards: { ...initialState },
    exam: { ...initialState },
  });

  const abortControllers = useRef<Record<TargetType, AbortController | null>>({
    quiz: null,
    notes: null,
    slides: null,
    flashcards: null,
    exam: null,
  });

  const updateState = useCallback((target: TargetType, update: Partial<GenerationState>) => {
    setStates(prev => ({
      ...prev,
      [target]: { ...prev[target], ...update },
    }));
  }, []);

  /**
   * Get auth token for backend requests 
   */
  const getAuthToken = async (): Promise<string | null> => {
    try {
      return await getAccessToken();
    } catch (error) {
      console.error('[ArtifactGenerator] Auth error:', error);
      return null;
    }
  };

  /**
   * Create a generate job via backend API
   */
  const createGenerateJob = async (
    projectId: string,
    sourceArtifactIds: string | string[],
    targetType: TargetType
  ): Promise<string> => {
    const token = await getAuthToken();

    console.log(`[ArtifactGenerator] Creating job: target=${targetType}, sources=${sourceArtifactIds}, project=${projectId}`);

    const payload: any = {
      target_type: targetType,
    };

    if (Array.isArray(sourceArtifactIds)) {
      payload.source_artifact_ids = sourceArtifactIds;
    } else {
      payload.source_artifact_id = sourceArtifactIds;
    }

    const res = await fetch(`${API_BASE}/api/jobs`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        project_id: projectId,
        type: 'generate',
        payload,
      }),
    });

    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Failed to create job' }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();
    return data.job_id;
  };

  /**
   * Poll job status until completion or failure
   */
  const pollJobStatus = async (
    jobId: string,
    target: TargetType,
    signal: AbortSignal
  ): Promise<{ artifactId: string | null; result: any }> => {
    const maxAttempts = 150; // 5 minutes at 2s intervals
    let attempts = 0;

    while (attempts < maxAttempts) {
      if (signal.aborted) {
        throw new Error('Generation cancelled');
      }

      const token = await getAuthToken();
      const res = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
        headers: token ? { 'Authorization': `Bearer ${token}` } : {}
      });
      if (!res.ok) {
        throw new Error(`Failed to fetch job status: ${res.status}`);
      }

      const data = await res.json();

      // Update progress estimate
      const progressMap: Record<string, number> = {
        'pending': 10,
        'running': 50,
        'completed': 100,
        'failed': 0,
      };
      updateState(target, { progress: progressMap[data.status] || 0 });

      if (data.status === 'completed') {
        return {
          artifactId: data.result?.artifact_id || null,
          result: data.result,
        };
      }

      if (data.status === 'failed') {
        throw new Error(data.error_message || 'Generation failed');
      }

      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, 2000));
      attempts++;
    }

    throw new Error('Generation timed out');
  };

  /**
   * Fetch artifact data from project artifacts
   */
  const fetchArtifact = async (
    projectId: string,
    artifactId: string
  ): Promise<Artifact | null> => {
    try {
      const { artifacts } = await api.projects.getArtifacts(projectId);
      return artifacts.find(a => a.id === artifactId) || null;
    } catch (error) {
      console.error('[ArtifactGenerator] Failed to fetch artifact:', error);
      return null;
    }
  };

  /**
   * Generate an artifact from a knowledge core (or list of sources)
   */
  const generate = useCallback(async (
    projectId: string,
    sourceArtifactIds: string | string[],
    targetType: TargetType
  ): Promise<Artifact | null> => {
    // Cancel any existing generation for this target
    if (abortControllers.current[targetType]) {
      abortControllers.current[targetType]?.abort();
    }

    const controller = new AbortController();
    abortControllers.current[targetType] = controller;

    // Reset state
    updateState(targetType, {
      ...initialState,
      status: 'pending',
      progress: 5,
    });

    const toastId = toast.loading(`Generating ${targetType}...`, {
      description: 'This may take a moment',
    });

    try {
      // Create job
      const jobId = await createGenerateJob(projectId, sourceArtifactIds, targetType);
      updateState(targetType, { jobId, status: 'running', progress: 20 });

      // Poll for completion
      const { artifactId, result } = await pollJobStatus(jobId, targetType, controller.signal);

      if (!artifactId) {
        throw new Error('No artifact ID in result');
      }

      // Fetch the artifact
      const artifact = await fetchArtifact(projectId, artifactId);

      if (!artifact) {
        throw new Error('Failed to fetch generated artifact');
      }

      updateState(targetType, {
        status: 'completed',
        artifactId,
        artifact,
        progress: 100,
      });

      toast.success(`${targetType} generated!`, {
        id: toastId,
        description: 'Click to view your artifact',
      });

      return artifact;

    } catch (error: any) {
      const message = error.message || 'Unknown error';

      if (message === 'Generation cancelled') {
        updateState(targetType, { ...initialState });
        toast.dismiss(toastId);
        return null;
      }

      updateState(targetType, {
        status: 'failed',
        error: message,
        progress: 0,
      });

      toast.error(`Failed to generate ${targetType}`, {
        id: toastId,
        description: message,
      });

      return null;

    } finally {
      abortControllers.current[targetType] = null;
    }
  }, [updateState]);

  /**
   * Cancel an ongoing generation
   */
  const cancel = useCallback((targetType: TargetType) => {
    if (abortControllers.current[targetType]) {
      abortControllers.current[targetType]?.abort();
      abortControllers.current[targetType] = null;
      updateState(targetType, { ...initialState });
      toast.info(`Cancelled ${targetType} generation`);
    }
  }, [updateState]);

  /**
   * Reset state for a target type
   */
  const reset = useCallback((targetType: TargetType) => {
    cancel(targetType);
    updateState(targetType, { ...initialState });
  }, [cancel, updateState]);

  /**
   * Reset all states
   */
  const resetAll = useCallback(() => {
    Object.keys(states).forEach(key => {
      reset(key as TargetType);
    });
  }, [reset, states]);

  /**
   * Check if any generation is in progress
   */
  const isGenerating = Object.values(states).some(
    s => s.status === 'pending' || s.status === 'running'
  );

  return {
    states,
    generate,
    cancel,
    reset,
    resetAll,
    isGenerating,
  };
}

/**
 * Find the knowledge core artifact for a project
 */
export async function findKnowledgeCore(projectId: string): Promise<Artifact | null> {
  try {
    const { artifacts } = await api.projects.getArtifacts(projectId);
    return artifacts.find(a => a.type === 'knowledge_core') || null;
  } catch (error) {
    console.error('[ArtifactGenerator] Failed to find knowledge core:', error);
    return null;
  }
}
