/**
 * Frontend Integration Harness
 * 
 * TEMPORARY FILE - DELETE AFTER VERIFICATION
 * 
 * This programmatically tests all job types over real HTTP.
 * No UI, no auth, just transport + orchestration validation.
 * 
 * Run this from browser console or a temporary dev page.
 */

import {
    ingestSource,
    generateArtifact,
    fetchProjectArtifacts,
    type JobStatus,
} from '../lib/jobApi';

// ============================================================================
// Configuration
// ============================================================================

const TEST_PROJECT_ID = '00000000-0000-0000-0000-000000000001';

// Use YouTube for testing (the only remote source that doesn't need local files)
const INGEST_SOURCE = {
    type: 'youtube' as const,
    ref: 'https://www.youtube.com/watch?v=R9OCA6UFE-0',
    name: 'TED-Ed Stoicism Video',
};

const TARGET_TYPES = ['quiz', 'exam', 'notes', 'slides', 'flashcards'] as const;

// ============================================================================
// Harness Functions
// ============================================================================

export async function runIntegrationHarness(): Promise<void> {
    console.log('============================================================');
    console.log('FRONTEND INTEGRATION HARNESS');
    console.log('============================================================');
    console.log(`Project ID: ${TEST_PROJECT_ID}`);
    console.log(`Source: ${INGEST_SOURCE.type} - ${INGEST_SOURCE.name}`);
    console.log('');

    const results: { step: string; status: 'PASS' | 'FAIL'; error?: string }[] = [];

    try {
        // Step 1: Ingest
        console.log('[1/3] Ingesting source...');
        const ingestResult = await ingestSource(
            TEST_PROJECT_ID,
            INGEST_SOURCE.type,
            INGEST_SOURCE.ref,
            INGEST_SOURCE.name
        );

        console.log(`✅ Ingest complete: ${ingestResult.result?.core_artifact_id}`);
        results.push({ step: 'Ingest', status: 'PASS' });

        const coreId = ingestResult.result?.core_artifact_id;
        if (!coreId) {
            throw new Error('No core_artifact_id in ingest result');
        }

        // Step 2: Generate all target types
        console.log('');
        console.log('[2/3] Generating all artifact types...');

        for (const targetType of TARGET_TYPES) {
            try {
                console.log(`  → Generating ${targetType}...`);
                const genResult = await generateArtifact(TEST_PROJECT_ID, coreId, targetType);
                console.log(`  ✅ ${targetType}: ${genResult.result?.artifact_id}`);
                results.push({ step: `Generate ${targetType}`, status: 'PASS' });
            } catch (e: any) {
                console.error(`  ❌ ${targetType}: ${e.message}`);
                results.push({ step: `Generate ${targetType}`, status: 'FAIL', error: e.message });
            }
        }

        // Step 3: Fetch all artifacts
        console.log('');
        console.log('[3/3] Fetching project artifacts...');
        const artifacts = await fetchProjectArtifacts(TEST_PROJECT_ID);
        console.log(`✅ Fetched ${artifacts.artifacts.length} artifacts, ${artifacts.edges.length} edges`);
        results.push({ step: 'Fetch Artifacts', status: 'PASS' });

    } catch (e: any) {
        console.error(`❌ Fatal error: ${e.message}`);
        results.push({ step: 'Fatal', status: 'FAIL', error: e.message });
    }

    // Summary
    console.log('');
    console.log('============================================================');
    console.log('SUMMARY');
    console.log('============================================================');

    const passed = results.filter((r) => r.status === 'PASS').length;
    const failed = results.filter((r) => r.status === 'FAIL').length;

    for (const r of results) {
        const icon = r.status === 'PASS' ? '✅' : '❌';
        console.log(`${icon} ${r.step}${r.error ? ` - ${r.error}` : ''}`);
    }

    console.log('');
    console.log(`Total: ${passed} passed, ${failed} failed`);

    if (failed === 0) {
        console.log('');
        console.log('🎉 FRONTEND INTEGRATION VERIFIED');
        console.log('You can now safely wire React Flow nodes.');
    }
}

/**
 * Quick test: just check if backend is reachable
 */
export async function testBackendConnection(): Promise<boolean> {
    try {
        const response = await fetch('http://localhost:8000/health');
        const data = await response.json();
        console.log('✅ Backend reachable:', data);
        return true;
    } catch (e: any) {
        console.error('❌ Backend unreachable:', e.message);
        return false;
    }
}

// Export to window for console access
if (typeof window !== 'undefined') {
    (window as any).integrationHarness = {
        run: runIntegrationHarness,
        testConnection: testBackendConnection,
    };
    console.log('[Integration Harness] Available in console:');
    console.log('  - integrationHarness.testConnection()');
    console.log('  - integrationHarness.run()');
}
