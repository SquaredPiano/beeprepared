'use client';

import { useState, useCallback, useRef, useEffect } from 'react';

const API_BASE = 'http://localhost:8000';
const TEST_PROJECT_ID = '00000000-0000-0000-0000-000000000001';

type SourceType = 'youtube' | 'audio' | 'video' | 'pdf' | 'pptx' | 'md';
type TargetType = 'quiz' | 'notes' | 'slides' | 'flashcards' | 'exam';
type JobStatus = 'idle' | 'pending' | 'running' | 'completed' | 'failed';

interface JobState {
    id: string | null;
    status: JobStatus;
    artifactId: string | null;
    artifact: any | null;
    error: string | null;
}

interface OrchestratorState {
    ingest: JobState;
    generate: Record<TargetType, JobState>;
}

const TARGETS: TargetType[] = ['quiz', 'notes', 'slides', 'flashcards', 'exam'];

const initialJobState: JobState = {
    id: null,
    status: 'idle',
    artifactId: null,
    artifact: null,
    error: null,
};

export function useJobOrchestrator() {
    const [state, setState] = useState<OrchestratorState>({
        ingest: { ...initialJobState },
        generate: {
            quiz: { ...initialJobState },
            notes: { ...initialJobState },
            slides: { ...initialJobState },
            flashcards: { ...initialJobState },
            exam: { ...initialJobState },
        },
    });

    const [isRunning, setIsRunning] = useState(false);
    const abortRef = useRef(false);

    // =========================================================================
    // API Helpers
    // =========================================================================

    const createJob = async (type: 'ingest' | 'generate', payload: any): Promise<string> => {
        const res = await fetch(`${API_BASE}/api/jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: TEST_PROJECT_ID, type, payload }),
        });
        if (!res.ok) throw new Error(`Create job failed: ${res.status}`);
        const data = await res.json();
        return data.job_id;
    };

    const pollJob = async (jobId: string): Promise<any> => {
        while (!abortRef.current) {
            const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
            const data = await res.json();
            if (data.status === 'completed') return data;
            if (data.status === 'failed') throw new Error(data.error_message || 'Job failed');
            await new Promise(r => setTimeout(r, 2000));
        }
        throw new Error('Aborted');
    };

    const fetchArtifact = async (artifactId: string): Promise<any> => {
        const res = await fetch(`${API_BASE}/api/projects/${TEST_PROJECT_ID}/artifacts`);
        const data = await res.json();
        return data.artifacts?.find((a: any) => a.id === artifactId) || null;
    };

    // =========================================================================
    // State Updaters
    // =========================================================================

    const updateIngest = useCallback((update: Partial<JobState>) => {
        setState(prev => ({ ...prev, ingest: { ...prev.ingest, ...update } }));
    }, []);

    const updateGenerate = useCallback((target: TargetType, update: Partial<JobState>) => {
        setState(prev => ({
            ...prev,
            generate: { ...prev.generate, [target]: { ...prev.generate[target], ...update } },
        }));
    }, []);

    // =========================================================================
    // Main Orchestration
    // =========================================================================

    const runPipeline = useCallback(async (
        sourceType: SourceType,
        sourceRef: string,
        originalName: string
    ) => {
        abortRef.current = false;
        setIsRunning(true);

        // Reset state
        setState({
            ingest: { ...initialJobState, status: 'pending' },
            generate: {
                quiz: { ...initialJobState },
                notes: { ...initialJobState },
                slides: { ...initialJobState },
                flashcards: { ...initialJobState },
                exam: { ...initialJobState },
            },
        });

        try {
            // ==== INGEST ====
            console.log('[Orchestrator] Starting ingest...');
            updateIngest({ status: 'pending' });

            const ingestJobId = await createJob('ingest', {
                source_type: sourceType,
                source_ref: sourceRef,
                original_name: originalName,
            });
            updateIngest({ id: ingestJobId, status: 'running' });

            const ingestResult = await pollJob(ingestJobId);
            const coreId = ingestResult.result?.core_artifact_id;

            if (!coreId) throw new Error('No core artifact ID from ingest');

            updateIngest({
                status: 'completed',
                artifactId: coreId,
            });
            console.log(`[Orchestrator] Ingest complete. Core ID: ${coreId}`);

            // ==== FAN-OUT GENERATE ====
            // Fire all 5 jobs concurrently, each updates independently
            TARGETS.forEach(async (target) => {
                if (abortRef.current) return;

                try {
                    updateGenerate(target, { status: 'pending' });

                    const genJobId = await createJob('generate', {
                        source_artifact_id: coreId,
                        target_type: target,
                    });
                    updateGenerate(target, { id: genJobId, status: 'running' });

                    const genResult = await pollJob(genJobId);
                    const artifactId = genResult.result?.artifact_id;

                    if (artifactId) {
                        const artifact = await fetchArtifact(artifactId);
                        updateGenerate(target, {
                            status: 'completed',
                            artifactId,
                            artifact,
                        });
                        console.log(`[Orchestrator] ${target} complete`);
                    } else {
                        updateGenerate(target, { status: 'failed', error: 'No artifact ID' });
                    }
                } catch (e: any) {
                    console.error(`[Orchestrator] ${target} failed:`, e.message);
                    updateGenerate(target, { status: 'failed', error: e.message });
                }
            });

        } catch (e: any) {
            console.error('[Orchestrator] Ingest failed:', e.message);
            updateIngest({ status: 'failed', error: e.message });
        }

        // Note: We don't await the generate promises, they complete independently
        // setIsRunning will stay true until user resets or page refresh
    }, [updateIngest, updateGenerate]);

    const abort = useCallback(() => {
        abortRef.current = true;
        setIsRunning(false);
    }, []);

    const reset = useCallback(() => {
        abortRef.current = true;
        setIsRunning(false);
        setState({
            ingest: { ...initialJobState },
            generate: {
                quiz: { ...initialJobState },
                notes: { ...initialJobState },
                slides: { ...initialJobState },
                flashcards: { ...initialJobState },
                exam: { ...initialJobState },
            },
        });
    }, []);

    // Check if all jobs are done
    const allDone = state.ingest.status === 'completed' &&
        TARGETS.every(t => ['completed', 'failed'].includes(state.generate[t].status));

    useEffect(() => {
        if (allDone && isRunning) {
            setIsRunning(false);
            console.log('[Orchestrator] All jobs complete');
        }
    }, [allDone, isRunning]);

    return {
        state,
        isRunning,
        runPipeline,
        abort,
        reset,
    };
}
