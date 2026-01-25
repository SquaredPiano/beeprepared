# Backend Setup & Integration Status

## Overview
We have prepared the backend for full integration with the "Auth & Projects" feature. The following components are ready:
1. **Job Runner (`backend/services/job_runner.py`)**: Now strictly monitors the queue and dispatches jobs to `IngestHandler` and `GenerateHandler`.
2. **Handlers**:
    - `backend/handlers/ingest_handler.py`: Validated.
    - `backend/handlers/generate_handler.py`: Validated.
3. **Database Migration**: `backend/db/migration_001_add_project_canvas_state.sql` handles schema updates for project canvas states.

## Action Required: Setup Environment
The current environment is missing critical dependencies and secrets. To finalize the integration:

### 1. Install Credentials
Ensure the `backend/.env` file contains your **real** Supabase and R2 credentials.
- `DATABASE_URL`: Must be the PostgreSQL connection string.
- `SUPABASE_URL` / `SUPABASE_KEY`: Service role key needed for RLS bypass in the runner.
- `R2_...`: Cloudflare R2 credentials for file storage.
- `GEMINI_API_KEY`: For AI processing.

### 2. Fix Python Environment
The local python environment (MinGW/MSYS) is missing `pip` and basic packages.
- Install standard Python 3.11+ for Windows (from python.org) if not present.
- Create a valid venv: `python -m venv venv`
- Activate: `.\venv\Scripts\activate`
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  pip install psycopg2-binary python-dotenv google-generativeai supabase openai pydantic boto3 yt-dlp ffmpeg-python
  ```

### 3. Run Database Migration
Once dependencies are installed and `.env` has the real `DATABASE_URL`:
```bash
python backend/scripts/apply_migration.py
```

### 4. Start the Job Runner
To start processing jobs (Ingestion -> Extraction -> Generation):
```bash
python backend/services/job_runner.py
```
This script will poll for "pending" jobs and execute strict logic.

## Remaining Todo
- Frontend "Bee Agent" branding (visual polish).
- Testing R2 integration end-to-end (requires keys).
- Verifying Canvas "Save State" after migration is applied.
