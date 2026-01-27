'use client';

import { useEffect, useState } from 'react';

/**
 * Dev Integration Page
 * 
 * TEMPORARY - DELETE AFTER VERIFICATION
 * 
 * This page programmatically tests the frontend → backend integration.
 * No auth, no canvas, just transport validation.
 */

interface Result {
    step: string;
    status: 'PASS' | 'FAIL' | 'RUNNING';
    error?: string;
}

const API_BASE = 'http://localhost:8000';
const TEST_PROJECT_ID = '00000000-0000-0000-0000-000000000001';

const INGEST_SOURCE = {
    type: 'youtube' as const,
    ref: 'https://www.youtube.com/watch?v=R9OCA6UFE-0',
    name: 'TED-Ed Stoicism Video',
};

const TARGET_TYPES = ['quiz', 'notes', 'slides', 'flashcards'] as const;

export default function DevIntegrationPage() {
    const [running, setRunning] = useState(false);
    const [results, setResults] = useState<Result[]>([]);
    const [logs, setLogs] = useState<string[]>([]);

    const log = (message: string) => {
        console.log(message);
        setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${message}`]);
    };

    const addResult = (step: string, status: 'PASS' | 'FAIL' | 'RUNNING', error?: string) => {
        setResults((prev) => {
            const existing = prev.findIndex((r) => r.step === step);
            if (existing >= 0) {
                const updated = [...prev];
                updated[existing] = { step, status, error };
                return updated;
            }
            return [...prev, { step, status, error }];
        });
    };

    const testConnection = async () => {
        log('Testing backend connection...');
        try {
            const res = await fetch(`${API_BASE}/health`);
            const data = await res.json();
            log(`✅ Backend reachable: ${JSON.stringify(data)}`);
            return true;
        } catch (e: any) {
            log(`❌ Backend unreachable: ${e.message}`);
            return false;
        }
    };

    const createJob = async (type: string, payload: any) => {
        const res = await fetch(`${API_BASE}/api/jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: TEST_PROJECT_ID,
                type,
                payload,
            }),
        });
        if (!res.ok) throw new Error(`Failed to create job: ${res.status}`);
        const data = await res.json();
        return data.job_id;
    };

    const pollJob = async (jobId: string): Promise<any> => {
        while (true) {
            const res = await fetch(`${API_BASE}/api/jobs/${jobId}`);
            const data = await res.json();

            if (data.status === 'completed') return data;
            if (data.status === 'failed') throw new Error(data.error_message);

            await new Promise((r) => setTimeout(r, 2000));
        }
    };

    const runHarness = async () => {
        setRunning(true);
        setResults([]);
        setLogs([]);

        log('============================================================');
        log('FRONTEND INTEGRATION HARNESS');
        log('============================================================');

        // Connection test
        const connected = await testConnection();
        if (!connected) {
            setRunning(false);
            return;
        }

        try {
            // Step 1: Ingest
            addResult('Ingest', 'RUNNING');
            log(`Ingesting ${INGEST_SOURCE.type}...`);

            const ingestJobId = await createJob('ingest', {
                source_type: INGEST_SOURCE.type,
                source_ref: INGEST_SOURCE.ref,
                original_name: INGEST_SOURCE.name,
            });
            log(`Created ingest job: ${ingestJobId}`);

            const ingestResult = await pollJob(ingestJobId);
            const coreId = ingestResult.result?.core_artifact_id;
            log(`✅ Ingest complete. Core ID: ${coreId}`);
            addResult('Ingest', 'PASS');

            if (!coreId) throw new Error('No core_artifact_id');

            // Step 2: Generate all types
            for (const targetType of TARGET_TYPES) {
                addResult(`Generate ${targetType}`, 'RUNNING');
                log(`Generating ${targetType}...`);

                try {
                    const genJobId = await createJob('generate', {
                        source_artifact_id: coreId,
                        target_type: targetType,
                    });
                    await pollJob(genJobId);
                    log(`✅ ${targetType} generated`);
                    addResult(`Generate ${targetType}`, 'PASS');
                } catch (e: any) {
                    log(`❌ ${targetType} failed: ${e.message}`);
                    addResult(`Generate ${targetType}`, 'FAIL', e.message);
                }
            }

            // Step 3: Fetch artifacts
            addResult('Fetch Artifacts', 'RUNNING');
            log('Fetching project artifacts...');
            const artRes = await fetch(`${API_BASE}/api/projects/${TEST_PROJECT_ID}/artifacts`);
            const artData = await artRes.json();
            log(`✅ Fetched ${artData.artifacts?.length || 0} artifacts, ${artData.edges?.length || 0} edges`);
            addResult('Fetch Artifacts', 'PASS');

            log('============================================================');
            log('🎉 INTEGRATION VERIFIED');
            log('============================================================');

        } catch (e: any) {
            log(`❌ Fatal error: ${e.message}`);
            addResult('Fatal', 'FAIL', e.message);
        }

        setRunning(false);
    };

    const passed = results.filter((r) => r.status === 'PASS').length;
    const failed = results.filter((r) => r.status === 'FAIL').length;

    return (
        <div style={{ padding: 40, fontFamily: 'monospace', background: '#0f172a', minHeight: '100vh', color: '#f8fafc' }}>
            <h1 style={{ marginBottom: 20, color: '#818cf8' }}>Frontend Integration Harness</h1>
            <p style={{ color: '#94a3b8', marginBottom: 20 }}>
                TEMPORARY - Tests all job types over real HTTP. Delete after verification.
            </p>

            <button
                onClick={runHarness}
                disabled={running}
                style={{
                    padding: '12px 24px',
                    background: running ? '#475569' : '#22c55e',
                    border: 'none',
                    borderRadius: 8,
                    color: 'white',
                    fontWeight: 'bold',
                    cursor: running ? 'not-allowed' : 'pointer',
                    marginBottom: 20,
                }}
            >
                {running ? 'Running...' : 'Run Integration Test'}
            </button>

            {results.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                    <h2 style={{ marginBottom: 10 }}>Results</h2>
                    {results.map((r) => (
                        <div key={r.step} style={{ marginBottom: 4 }}>
                            {r.status === 'PASS' && '✅'}
                            {r.status === 'FAIL' && '❌'}
                            {r.status === 'RUNNING' && '⏳'}
                            {' '}{r.step}
                            {r.error && <span style={{ color: '#ef4444' }}> - {r.error}</span>}
                        </div>
                    ))}
                    <div style={{ marginTop: 10, fontWeight: 'bold' }}>
                        Total: {passed} passed, {failed} failed
                    </div>
                </div>
            )}

            <h2 style={{ marginBottom: 10 }}>Logs</h2>
            <div style={{
                background: '#1e293b',
                padding: 16,
                borderRadius: 8,
                maxHeight: 400,
                overflow: 'auto',
                fontSize: 12,
            }}>
                {logs.map((l, i) => (
                    <div key={i}>{l}</div>
                ))}
                {logs.length === 0 && <span style={{ color: '#64748b' }}>Click "Run Integration Test" to start</span>}
            </div>
        </div>
    );
}
