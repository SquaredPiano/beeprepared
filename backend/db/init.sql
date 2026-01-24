-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Lectures Table
CREATE TABLE IF NOT EXISTS public.lectures (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL, -- 'audio', 'video', 'pdf', 'pptx', 'docx', 'text', 'markdown', 'youtube'
    file_url TEXT NOT NULL,
    file_size_bytes BIGINT,
    duration_seconds INTEGER,
    status TEXT DEFAULT 'processing', -- 'processing', 'complete', 'failed'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Transcripts Table (Stores raw extracted text)
CREATE TABLE IF NOT EXISTS public.transcripts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lecture_id UUID REFERENCES public.lectures(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    language TEXT,
    duration_seconds DOUBLE PRECISION,
    structured_data JSONB, -- stores words/timestamps if available
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Processing Tasks Table (For polling)
CREATE TABLE IF NOT EXISTS public.processing_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lecture_id UUID REFERENCES public.lectures(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'queued', -- 'queued', 'processing', 'complete', 'failed'
    current_stage TEXT, -- 'uploading', 'transcribing', 'extracting'
    progress INTEGER DEFAULT 0,
    bee_worker TEXT, -- 'transcriber', 'extractor'
    estimated_seconds_remaining INTEGER,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Auto-update timestamps
CREATE OR REPLACE FUNCTION update_modified_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Drop triggers if they exist to avoid errors on re-run
DROP TRIGGER IF EXISTS update_lectures_modtime ON public.lectures;
DROP TRIGGER IF EXISTS update_tasks_modtime ON public.processing_tasks;

CREATE TRIGGER update_lectures_modtime
    BEFORE UPDATE ON public.lectures
    FOR EACH ROW
    EXECUTE PROCEDURE update_modified_column();

CREATE TRIGGER update_tasks_modtime
    BEFORE UPDATE ON public.processing_tasks
    FOR EACH ROW
    EXECUTE PROCEDURE update_modified_column();
