-- Add user_id to projects for multi-tenancy
-- Run this AFTER the main schema.sql has been applied

ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE;

-- Create index for user lookups
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON public.projects(user_id);

-- Enable Row Level Security
ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.artifact_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.renderings ENABLE ROW LEVEL SECURITY;

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

-- Remove test project (has no user_id)
DELETE FROM public.projects WHERE id = '00000000-0000-0000-0000-000000000001';
