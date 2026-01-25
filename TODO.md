# BeePrepared - Integration TODO

## Completed ✅
- Auth flow integrated with Supabase
- Backend API endpoints for projects and upload
- Frontend API client with proper TypeScript types
- Canvas store with artifact-to-node conversion
- ArtifactNode component for displaying artifacts
- File upload flow with job polling
- Backend simplified to use httpx instead of problematic supabase SDK
- Test script created for simulating user flows
- Basic CRUD endpoints working

## In Progress 🔄

### Database Migration
- **Priority: HIGH**
- Apply `backend/db/migration_001_add_project_canvas_state.sql` to Supabase database
- Adds `user_id` and `canvas_state` columns to projects table
- Sets up RLS policies for all tables (projects, artifacts, artifact_edges, jobs, renderings)
- **Current Status**: Migration file created but not applied. Backend currently works without these columns via graceful fallbacks.

### Job Runner Integration
- **Priority: HIGH**
- The job runner (`backend/job_runner.py`) needs to be running as a separate process
- Jobs are created but not processed (test showed timeout waiting for job completion)
- Need to either:
  - Start job runner as background service: `python -m backend.job_runner`
  - Or integrate into main API as background task
- **Test Result**: Jobs create successfully but don't complete (expected without runner)

### R2 Storage Integration
- **Priority: MEDIUM**
- Currently files upload to temp directory on backend server
- Need to integrate Cloudflare R2 for persistent storage
- Update upload endpoint to save to R2 instead of temp files
- Store R2 URLs in artifact content
- Implement proper auth/credential handling per user

### "Add New Content" Page Redesign
- **Priority: MEDIUM**
- Current upload modal works but needs full redesign
- Make it bee-themed (bee agents branding)
- Better UX for file selection and progress
- Show artifact generation pipeline visually
- Location: `frontend/components/canvas/AssetUploadModal.tsx`

## Bugs to Fix 🐛

### Canvas Save Failure
- **Status**: Fixed with graceful fallback
- Frontend save now works even without `canvas_state` column
- Once migration is applied, will save full canvas state
- Current behavior: Saves project metadata, skips canvas_state if column missing

### Generate Job Payload
- **Status**: Partially fixed
- GeneratePayload validation expects specific fields
- Test updated but still getting 400 errors
- Need to verify payload structure matches backend expectations

## Testing Needed 🧪

### Manual Testing Checklist
- [ ] Create new project via frontend
- [ ] Upload file (PDF, video, audio)
- [ ] Verify job polling shows progress
- [ ] Check artifacts appear on canvas after processing
- [ ] Test canvas save/load with positions
- [ ] Verify delete operations work
- [ ] Test generate operations (quiz, flashcards, etc.)

### Automated Tests
- **Location**: `backend/scripts/test_user_flow.py`
- **Status**: Basic flow tests passing
- **Coverage**: 
  - ✅ Health check
  - ✅ Project create
  - ✅ File upload
  - ⏸️ Job completion (needs runner)
  - ✅ Artifact listing
  - ❌ Generate operations (payload issues)

## Architecture Improvements 📐

### Bee Agent Branding
- Add bee-themed terminology throughout:
  - Workers → Bee Workers
  - Processing → Honey Making
  - Artifacts → Honey Combs / Bee Products
  - Jobs → Bee Tasks
- Update UI components with bee imagery
- Add bee mascot interactions
- Honeycomb-style data visualization

### Frontend Polish
- Improve loading states with bee animations
- Add success/error notifications with bee themes
- Better empty states
- Improve mobile responsiveness
- Add keyboard shortcuts

### Backend Improvements
- Add proper error logging
- Implement rate limiting
- Add job retry logic
- Improve job status webhooks/SSE for real-time updates
- Add job cancellation endpoint

## Deployment Prep 🚀

### Environment Variables Needed
```
# Backend
SUPABASE_URL=<your-url>
SUPABASE_SERVICE_ROLE_KEY=<your-key>
OPENAI_API_KEY=<your-key>
R2_ACCOUNT_ID=<cloudflare-account>
R2_ACCESS_KEY_ID=<r2-key>
R2_SECRET_ACCESS_KEY=<r2-secret>
R2_BUCKET_NAME=beeprepared-assets

# Frontend  
NEXT_PUBLIC_SUPABASE_URL=<your-url>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your-anon-key>
NEXT_PUBLIC_BACKEND_URL=<backend-url>
```

### Database Setup
1. Run migration: `backend/db/migration_001_add_project_canvas_state.sql`
2. Verify RLS policies are active
3. Test with non-service-role credentials
4. Remove DEV_MODE bypass from auth

### Process Management
- Backend API: Uvicorn with gunicorn
- Job Runner: Supervisor or systemd service
- Frontend: Vercel deployment (already configured)

## Quick Start After Battery Charge ⚡

1. **Apply Migration**:
   ```sql
   -- Run backend/db/migration_001_add_project_canvas_state.sql in Supabase SQL editor
   ```

2. **Start Job Runner**:
   ```bash
   cd backend
   python -m backend.job_runner
   ```

3. **Test Full Flow**:
   ```bash
   # Terminal 1: Backend
   cd backend
   uvicorn api:app --reload
   
   # Terminal 2: Job Runner
   cd backend
   python -m backend.job_runner
   
   # Terminal 3: Frontend
   cd frontend
   npm run dev
   
   # Terminal 4: Test
   cd backend
   python scripts/test_user_flow.py
   ```

4. **Verify Canvas Save**:
   - Create project in UI
   - Add some nodes
   - Move them around
   - Click save
   - Refresh page
   - Positions should restore

## Notes 📝

- Backend running on http://localhost:8000
- Frontend running on http://localhost:3000
- Test data: 18 artifacts exist from previous tests (can delete via `/api/projects/{id}` DELETE endpoint)
- Supabase SDK replaced with simple httpx client due to Windows build issues
- DEV_MODE still enabled in MainLayoutWrapper for easy testing
