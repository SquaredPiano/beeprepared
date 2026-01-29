-- Canonical Database Schema for BeePrepared Knowledge Graph
-- Phase 1 of System Re-Architecture
-- Source of Truth: backend/schema.sql

-- Enable UUID extension for ID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==========================================
-- 1. Projects
-- ==========================================
-- Root container for a user's workspace/graph.
CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ==========================================
-- 4. Jobs (Defined before artifacts because artifacts reference jobs)
-- ==========================================
-- Tracks all asynchronous operations.
CREATE TYPE job_type AS ENUM (
    'ingest', 
    'extract', 
    'clean', 
    'generate', 
    'render'
);

CREATE TYPE job_status AS ENUM (
    'pending', 
    'running', 
    'completed', 
    'failed'
);

CREATE TABLE IF NOT EXISTS public.jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    type job_type NOT NULL,
    status job_status NOT NULL DEFAULT 'pending',
    
    -- Arguments for the job
    payload JSONB NOT NULL DEFAULT '{}',
    
    -- Output: {'artifact_ids': [...], 'error': ...}
    -- Note: Ideally this is empty, as artifacts link back to jobs. 
    -- Kept for lightweight errors or summaries.
    result JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    error_message TEXT
);

-- INVARIANT: Jobs cannot overwrite reality.
-- A completed job is a historical fact. It cannot be modified.
CREATE OR REPLACE FUNCTION prevent_job_history_rewrite()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'Cannot modify a finalized job. Jobs are immutable history.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_job_immutable_history
    BEFORE UPDATE ON public.jobs
    FOR EACH ROW
    EXECUTE PROCEDURE prevent_job_history_rewrite();

-- ==========================================
-- 2. Artifacts
-- ==========================================
-- Immutable nodes in the knowledge graph.
-- Once created, an artifact is NEVER updated.
CREATE TYPE artifact_type AS ENUM (
    'video', 
    'audio', 
    'text',       -- Raw text
    'flat_text',  -- Cleaned text
    'knowledge_core', 
    'quiz', 
    'flashcards', 
    'notes', 
    'slides', 
    'exam'
);

CREATE TABLE IF NOT EXISTS public.artifacts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    type artifact_type NOT NULL,
    content JSONB NOT NULL, -- Format-agnostic data
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Provenance: Which job created this?
    -- This enforces "Jobs produce artifacts".
    created_by_job_id UUID REFERENCES public.jobs(id)
    
    -- No updated_at because artifacts are immutable
);

-- INVARIANT: Artifacts are ostensibly immutable, but we allow updates for "Notes" 
-- and manual corrections. The strict trigger has been removed to allow valid PUT/PATCH operations.
-- Applications should generally prefer creating new versions, but in-place edits are permitted.

-- INVARIANT: Job-Artifact Project Consistency.
-- An artifact created by a job must belong to the same project as the job.
CREATE OR REPLACE FUNCTION check_job_artifact_consistency()
RETURNS TRIGGER AS $$
DECLARE
    job_pid UUID;
BEGIN
    -- If created_by_job_id is NULL, it's a legacy or manual artifact. Allow.
    IF NEW.created_by_job_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT project_id INTO job_pid FROM jobs WHERE id = NEW.created_by_job_id;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Foreign Key Violation: Job % does not exist.', NEW.created_by_job_id;
    END IF;

    IF NEW.project_id <> job_pid THEN
        RAISE EXCEPTION 'Invariant Violation: Project Mismatch. Artifact project (%) must match Job project (%).', NEW.project_id, job_pid;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_enforce_job_artifact_consistency
    BEFORE INSERT ON public.artifacts
    FOR EACH ROW
    EXECUTE PROCEDURE check_job_artifact_consistency();

-- ==========================================
-- 3. Artifact Edges
-- ==========================================
-- Represents the DAG structure (Dependency / Provenance).
-- "Child was derived from Parent"
CREATE TYPE edge_type AS ENUM (
    'derived_from', -- General derivation (e.g. Cleaned Text -> Raw Text)
    'contains',     -- Hierarchical (e.g. Knowledge Core -> Concept)
    'references'    -- Loose reference
);

CREATE TABLE IF NOT EXISTS public.artifact_edges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    parent_artifact_id UUID NOT NULL REFERENCES public.artifacts(id) ON DELETE RESTRICT, -- Prevent deleting history
    child_artifact_id UUID NOT NULL REFERENCES public.artifacts(id) ON DELETE CASCADE,
    relationship_type edge_type NOT NULL DEFAULT 'derived_from',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_edge UNIQUE (parent_artifact_id, child_artifact_id, relationship_type)
);

-- INVARIANT: No Cycles (DAG Integrity).
-- A child cannot be an ancestor of its parent.
CREATE OR REPLACE FUNCTION check_dag_cycle()
RETURNS TRIGGER AS $$
DECLARE
    cycle_exists BOOLEAN;
BEGIN
    -- Check if adding this edge (parent -> child) creates a path from child -> parent
    WITH RECURSIVE lineage AS (
        -- Base case: edges where 'parent' is our new child
        SELECT child_artifact_id 
        FROM artifact_edges 
        WHERE parent_artifact_id = NEW.child_artifact_id
        
        UNION
        
        -- Recursive: follow down the children
        SELECT e.child_artifact_id 
        FROM artifact_edges e
        INNER JOIN lineage l ON e.parent_artifact_id = l.child_artifact_id
    )
    SELECT EXISTS (
        SELECT 1 FROM lineage WHERE child_artifact_id = NEW.parent_artifact_id
    ) INTO cycle_exists;
    
    IF cycle_exists THEN
        RAISE EXCEPTION 'Cycle detected. Artifact % cannot be an ancestor of %', NEW.child_artifact_id, NEW.parent_artifact_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_prevent_cycles
    BEFORE INSERT ON public.artifact_edges
    FOR EACH ROW
    EXECUTE PROCEDURE check_dag_cycle();

-- INVARIANT: Knowledge Core is the Semantic Root (Indegree = 0).
-- A knowledge_core artifact cannot be the child in any relationship.
CREATE OR REPLACE FUNCTION check_knowledge_core_root()
RETURNS TRIGGER AS $$
DECLARE
    child_type artifact_type;
BEGIN
    SELECT type INTO child_type FROM artifacts WHERE id = NEW.child_artifact_id;
    
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Foreign Key Violation: Artifact % does not exist.', NEW.child_artifact_id;
    END IF;

    IF child_type = 'knowledge_core' THEN
         RAISE EXCEPTION 'Invariant Violation: knowledge_core artifacts must be roots (indegree=0). They cannot be children.';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_enforce_knowledge_core_root
    BEFORE INSERT ON public.artifact_edges
    FOR EACH ROW
    EXECUTE PROCEDURE check_knowledge_core_root();


-- INVARIANT: Project Isolation.
-- Edges can only exist between artifacts in the same project.
CREATE OR REPLACE FUNCTION check_project_isolation()
RETURNS TRIGGER AS $$
DECLARE
    parent_pid UUID;
    child_pid UUID;
BEGIN
    SELECT project_id INTO parent_pid FROM artifacts WHERE id = NEW.parent_artifact_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Foreign Key Violation: Parent Artifact % does not exist.', NEW.parent_artifact_id;
    END IF;

    SELECT project_id INTO child_pid FROM artifacts WHERE id = NEW.child_artifact_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Foreign Key Violation: Child Artifact % does not exist.', NEW.child_artifact_id;
    END IF;

    IF parent_pid <> child_pid THEN
        RAISE EXCEPTION 'Invariant Violation: Cross-Project Edge detected. Parent % (Project %) cannot link to Child % (Project %).', NEW.parent_artifact_id, parent_pid, NEW.child_artifact_id, child_pid;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_enforce_project_isolation
    BEFORE INSERT ON public.artifact_edges
    FOR EACH ROW
    EXECUTE PROCEDURE check_project_isolation();


-- ==========================================
-- 5. Renderings
-- ==========================================
-- Materialized views of artifacts (Files stored on R2/S3).
-- These are "Exportable" formats derived from an Artifact.
CREATE TYPE render_format AS ENUM (
    'pdf', 
    'pptx', 
    'mp3', 
    'mp4',
    'json',
    'md',
    'tex'
);

CREATE TABLE IF NOT EXISTS public.renderings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES public.artifacts(id) ON DELETE CASCADE,
    format render_format NOT NULL,
    
    -- Storage path (e.g. r2://bucket/path/to/file.ext)
    r2_path TEXT NOT NULL,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- INVARIANT: Unique renderings per artifact.
    -- Prevents multiple PDFs for the same artifact.
    CONSTRAINT unique_rendering_per_artifact UNIQUE (artifact_id, format)
);

-- Indexes for performance
CREATE INDEX idx_artifacts_project_id ON public.artifacts(project_id);
CREATE INDEX idx_artifacts_type ON public.artifacts(type);
CREATE INDEX idx_edges_parent ON public.artifact_edges(parent_artifact_id);
CREATE INDEX idx_edges_child ON public.artifact_edges(child_artifact_id);
CREATE INDEX idx_jobs_project_status ON public.jobs(project_id, status);
CREATE INDEX idx_renderings_artifact ON public.renderings(artifact_id);

-- Auto-update trigger for Projects (only table with updated_at)
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_projects_modtime
    BEFORE UPDATE ON public.projects
    FOR EACH ROW
    EXECUTE PROCEDURE update_modified_column();

-- ==========================================
-- 6. Job Runner Functions (RPC)
-- ==========================================

-- Atomically claim the next pending job for a given project (or any project).
-- Returns the full job row.
CREATE OR REPLACE FUNCTION claim_next_job()
RETURNS TABLE (
    j_id UUID,
    j_project_id UUID,
    j_type job_type,
    j_status job_status,
    j_payload JSONB,
    j_result JSONB,
    j_created_at TIMESTAMP WITH TIME ZONE,
    j_started_at TIMESTAMP WITH TIME ZONE,
    j_completed_at TIMESTAMP WITH TIME ZONE,
    j_error_message TEXT
) AS $$
BEGIN
    RETURN QUERY
    UPDATE jobs
    SET 
        status = 'running',
        started_at = NOW()
    WHERE id = (
        SELECT id
        FROM jobs
        WHERE status = 'pending'
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING 
        id, 
        project_id, 
        type, 
        status, 
        payload, 
        result, 
        created_at, 
        started_at, 
        completed_at, 
        error_message;
END;
$$ LANGUAGE plpgsql;

-- Atomically commit the results of a job (Artifacts, Edges, Renderings, Job Status).
CREATE OR REPLACE FUNCTION commit_job_bundle(
    _job_id UUID,
    _project_id UUID, -- Redundant but good for validation if needed
    _artifacts JSONB, -- List of artifact objects
    _edges JSONB,     -- List of edge objects
    _renderings JSONB,-- List of rendering objects
    _result JSONB     -- Final job result metadata
)
RETURNS VOID AS $$
DECLARE
    a_rec JSONB;
BEGIN
    -- 1. Insert Artifacts
    -- Note: We force created_by_job_id to be _job_id to ensure provenance.
    INSERT INTO artifacts (id, project_id, type, content, created_by_job_id)
    SELECT 
        (x->>'id')::UUID,
        (x->>'project_id')::UUID,
        (x->>'type')::artifact_type,
        (x->'content'),
        _job_id
    FROM jsonb_array_elements(_artifacts) x;

    -- 2. Insert Edges
    INSERT INTO artifact_edges (parent_artifact_id, child_artifact_id, relationship_type, project_id)
    SELECT 
        (x->>'parent_artifact_id')::UUID,
        (x->>'child_artifact_id')::UUID,
        (x->>'relationship_type')::edge_type,
        (x->>'project_id')::UUID
    FROM jsonb_array_elements(_edges) x;

    -- 3. Insert Renderings
    INSERT INTO renderings (project_id, artifact_id, format, r2_path)
    SELECT 
        (x->>'project_id')::UUID,
        (x->>'artifact_id')::UUID,
        (x->>'format')::render_format,
        (x->>'r2_path')
    FROM jsonb_array_elements(_renderings) x;

    -- 4. Complete Job
    UPDATE jobs 
    SET 
        status = 'completed', 
        result = _result, 
        completed_at = NOW() 
    WHERE id = _job_id;
    
    -- Trigger 'trigger_job_immutable_history' will protect against re-completing.
END;
$$ LANGUAGE plpgsql;
