# TODO: Auth & Projects Integration - Remaining Work

## Current Status
✅ Backend API endpoints created (POST /projects, POST /projects/{id}/upload, DELETE /projects/{id})
✅ Frontend API client rewritten with proper types
✅ Canvas store updated with artifact-to-node conversion
✅ ArtifactNode component created for displaying artifacts
✅ Upload flow works (file → backend → ingest job → poll → artifacts)
✅ Test script created and verified core functionality

## Critical: Database Migration Required
**MUST RUN BEFORE PRODUCTION:**
```sql
-- File: backend/db/migration_001_add_project_canvas_state.sql
-- Adds user_id and canvas_state columns to projects table
-- Adds RLS policies for all tables
```

**How to apply:**
1. Go to Supabase dashboard → SQL Editor
2. Copy/paste migration file contents
3. Run the migration
4. Verify with: `SELECT user_id, canvas_state FROM projects LIMIT 1;`

## Remaining Work

### 1. Bee Agent Branding 🐝
- [ ] Update terminology throughout app (workers → bee agents)
- [ ] Add bee-themed animations to processing states
- [ ] Update ArtifactNode to show "bee workers" processing
- [ ] Add honeycomb patterns to background of processing states
- [ ] Worker pipeline should show bees flying between hexagons
- [ ] "Hive mind" concept for knowledge_core

### 2. Add New Content Page Redesign
**File:** `frontend/app/dashboard/library/page.tsx`
- [ ] Full UI redesign with bee theme
- [ ] Hook up to Cloudflare R2 for asset storage (not Supabase storage)
- [ ] Use user credentials from auth for R2 access control
- [ ] Upload flow: File → R2 bucket → Store R2 URL in database
- [ ] Grid view of uploaded assets with previews
- [ ] Bee-themed upload dropzone

### 3. Canvas State Saving Fix
**Current Issue:** Save fails because `canvas_state` column doesn't exist yet
**Solution:**
- [x] Made save graceful - won't fail if column missing
- [x] Apply migration to add column (Script created: `backend/scripts/apply_migration.py`, requires `DATABASE_URL`)
- [ ] Test save/load after migration

### 4. Job Runner Process
**Currently:** Jobs are created but not processed (no worker running)
**File:** `backend/services/job_runner.py`
- [ ] Create systemd/Windows service for job runner
- [ ] Or: Add background task in FastAPI with `asyncio`
- [x] Monitor jobs table for pending jobs (Implemented in `job_runner.py`)
- [x] Process: ingest → extract → generate → render (Dispatch logic added)
- [x] Update job status and result fields

### 5. R2 Integration for Assets
**Files to modify:**
- `backend/api.py` - Add R2 upload endpoint
- `frontend/lib/api.ts` - Add R2 upload method
- `backend/.env` - Add R2 credentials

**Flow:**
```
User uploads → Frontend → Backend /upload-to-r2
                          ↓
                    Upload to R2 bucket
                          ↓
                    Return R2 URL
                          ↓
            Store in artifacts.content.url
```

**R2 Setup:**
- Create Cloudflare R2 bucket: `beeprepared-assets`
- Generate R2 API token
- Add to `.env`: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY`, `R2_SECRET_KEY`, `R2_BUCKET_NAME`
- Use boto3 (S3-compatible) client for uploads

### 6. User Testing & Flow Verification
- [ ] Manual test: Sign up → Create project → Upload file → View canvas
- [ ] Verify artifacts appear on canvas after processing
- [ ] Test job polling with actual backend runner
- [ ] Test generate endpoints (quiz, flashcards, notes, slides, exam)
- [ ] Verify RLS policies work (users can't access other users' projects)

### 7. Frontend Improvements
- [ ] Add loading states with bee animations
- [ ] Error handling with retry logic
- [ ] Toast notifications for operations
- [ ] Optimistic updates for better UX
- [ ] Canvas auto-layout for new artifacts

### 8. Backend Improvements
- [ ] Add rate limiting
- [ ] Add request validation middleware
- [ ] Improve error responses (consistent format)
- [ ] Add logging for debugging
- [ ] Add health check for job runner status

## Quick Wins (Low Effort, High Impact)
1. **Bee mascot animations** - Add flying bee during upload/processing
2. **Honeycomb loading spinner** - Replace generic loaders
3. **"Hive" terminology** - Projects → Hives, Artifacts → Honeycomb cells
4. **Buzzing sound effects** (optional) - On file upload complete

## Environment Variables Needed
```bash
# Backend (.env)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-key
SUPABASE_ANON_KEY=your-anon-key
DEEPGRAM_API_KEY=your-deepgram-key
ANTHROPIC_API_KEY=your-anthropic-key
R2_ACCOUNT_ID=your-r2-account-id
R2_ACCESS_KEY=your-r2-access-key
R2_SECRET_KEY=your-r2-secret-key
R2_BUCKET_NAME=beeprepared-assets

# Frontend (.env.local)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_R2_PUBLIC_URL=https://your-r2-bucket.r2.dev
```

## Testing Script
Run: `python backend/scripts/test_user_flow.py --backend http://localhost:8000`

**Current Results:**
- ✅ Backend health check
- ✅ Project creation
- ✅ File upload
- ⏳ Job processing (requires job runner)
- ✅ Artifact retrieval
- ⚠️ Generate job (needs correct payload format)

## Next Session Priorities
1. Apply database migration
2. Implement bee agent branding
3. Set up R2 for asset storage
4. Start job runner process
5. Test full end-to-end flow

## Notes
- Backend uses simplified Supabase client (httpx) to avoid Windows build issues
- Frontend has DEV_MODE bypass still enabled in auth
- Canvas state is stored in projects table (viewport + node positions)
- Artifacts are separate table with parent/child edges for lineage
