-- Migration 001: Add user_id and canvas_state to projects
-- Run this AFTER schema.sql has been applied

-- Add user_id for multi-tenancy (references Supabase auth.users)
ALTER TABLE public.projects 
ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

-- Add canvas_state to store React Flow viewport and node positions
-- This is UI state, not semantic data, so it's stored here not in artifacts
ALTER TABLE public.projects
ADD COLUMN IF NOT EXISTS canvas_state JSONB DEFAULT '{"viewport": {"x": 0, "y": 0, "zoom": 1}, "node_positions": {}}'::jsonb;

-- Create index for user lookups
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON public.projects(user_id);

-- Enable Row Level Security on all tables
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifact_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.renderings ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if they exist (for idempotency)
DROP POLICY IF EXISTS "Users can CRUD own projects" ON public.projects;
DROP POLICY IF EXISTS "Users can CRUD own artifacts" ON public.artifacts;
DROP POLICY IF EXISTS "Users can CRUD own edges" ON public.artifact_edges;
DROP POLICY IF EXISTS "Users can CRUD own jobs" ON public.jobs;
DROP POLICY IF EXISTS "Users can CRUD own renderings" ON public.renderings;

-- RLS Policies: Users can only see/modify their own projects and related data
CREATE POLICY "Users can CRUD own projects" ON public.projects
    FOR ALL USING (auth.uid() = user_id);

CREATE POLICY "Users can CRUD own artifacts" ON public.artifacts
    FOR ALL USING (project_id IN (SELECT id FROM projects WHERE user_id = auth.uid()));

CREATE POLICY "Users can CRUD own edges" ON public.artifact_edges
    FOR ALL USING (project_id IN (SELECT id FROM projects WHERE user_id = auth.uid()));

CREATE POLICY "Users can CRUD own jobs" ON public.jobs
    FOR ALL USING (project_id IN (SELECT id FROM projects WHERE user_id = auth.uid()));

CREATE POLICY "Users can CRUD own renderings" ON public.renderings
    FOR ALL USING (project_id IN (SELECT id FROM projects WHERE user_id = auth.uid()));

-- Service role bypass for backend processing
CREATE POLICY "Service role bypass projects" ON public.projects
    FOR ALL USING (auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role bypass artifacts" ON public.artifacts
    FOR ALL USING (auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role bypass edges" ON public.artifact_edges
    FOR ALL USING (auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role bypass jobs" ON public.jobs
    FOR ALL USING (auth.jwt()->>'role' = 'service_role');

CREATE POLICY "Service role bypass renderings" ON public.renderings
    FOR ALL USING (auth.jwt()->>'role' = 'service_role');
