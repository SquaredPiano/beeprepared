# BeePrepared API Contract

**Status:** FROZEN  
**Base URL:** `http://localhost:8000`

---

## Endpoints

### 0. Health Check

```http
GET /health
```

**Response (200):**
```json
{ "status": "healthy" }
```

---

### 1. Create Job

```http
POST /api/jobs
Content-Type: application/json
```

**Request (Ingest):**
```json
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "type": "ingest",
  "payload": {
    "source_type": "youtube",
    "source_ref": "https://www.youtube.com/watch?v=...",
    "original_name": "Lecture 1"
  }
}
```

**Request (Generate):**
```json
{
  "project_id": "00000000-0000-0000-0000-000000000001",
  "type": "generate",
  "payload": {
    "source_artifact_id": "<uuid of knowledge_core>",
    "target_type": "quiz"
  }
}
```

**Response (201):**
```json
{
  "job_id": "eccb334d-dc1b-4e91-90ea-daed20f22de0"
}
```

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 400 | Invalid job type | `{"detail": "Invalid job type: foo"}` |
| 400 | Missing payload field | `{"detail": "Invalid ingest payload: ..."}` |
| 400 | Invalid source_type | `{"detail": "Invalid source_type: abc"}` |
| 400 | Invalid target_type | `{"detail": "Invalid target_type: xyz"}` |
| 400 | Artifact not found | `{"detail": "Source artifact not found"}` |
| 400 | Illegal generation | `{"detail": "Cannot generate exam from quiz"}` |

---

### 2. Poll Job Status

```http
GET /api/jobs/{job_id}
```

**Response (200):**
```json
{
  "id": "eccb334d-dc1b-4e91-90ea-daed20f22de0",
  "project_id": "00000000-0000-0000-0000-000000000001",
  "type": "ingest",
  "status": "completed",
  "payload": { ... },
  "result": {
    "status": "success",
    "source_artifact_id": "<uuid>",
    "core_artifact_id": "<uuid>"
  },
  "error_message": null
}
```

**Status values:**
- `pending` — Job created, waiting for runner
- `running` — Job is being processed
- `completed` — Job finished successfully
- `failed` — Job failed (check `error_message`)

**Error Responses:**

| Status | Condition | Body |
|--------|-----------|------|
| 404 | Job not found | `{"detail": "Job not found"}` |

---

### 3. List Project Artifacts

```http
GET /api/projects/{project_id}/artifacts
```

**Response (200):**
```json
{
  "artifacts": [
    {
      "id": "<uuid>",
      "project_id": "<uuid>",
      "type": "youtube",
      "content": { "kind": "source", ... },
      "created_at": "..."
    },
    {
      "id": "<uuid>",
      "project_id": "<uuid>",
      "type": "knowledge_core",
      "content": { "kind": "core", "core": { ... } },
      "created_at": "..."
    }
  ],
  "edges": [
    {
      "id": "<uuid>",
      "parent_artifact_id": "<uuid>",
      "child_artifact_id": "<uuid>",
      "relationship_type": "derived_from"
    }
  ]
}
```

---

## Frontend Flow

```
1. User uploads/selects source
   → POST /api/jobs { type: "ingest", ... }
   → Save job_id
   → Set node state: "loading"

2. Poll every 2s
   → GET /api/jobs/{job_id}
   → If status == "running": continue
   → If status == "completed": 
       • Extract artifact IDs from result
       • Set node state: "ready"
       • Enable "Generate Quiz" button
   → If status == "failed":
       • Show error_message
       • Set node state: "error"

3. User clicks "Generate Quiz"
   → POST /api/jobs { type: "generate", source_artifact_id, target_type: "quiz" }
   → Same polling loop

4. After all jobs complete
   → GET /api/projects/{project_id}/artifacts
   → Render full graph in React Flow
```

---

## Valid Job Types

| type | payload |
|------|---------|
| `ingest` | `{ source_type, source_ref, original_name }` |
| `generate` | `{ source_artifact_id, target_type }` |

## Valid source_type

`youtube`, `audio`, `video`, `pdf`, `pptx`, `md`

## Valid target_type

`quiz`, `exam`, `notes`, `slides`, `flashcards`

## Allowed Generation Paths

| Source Type | Can Generate |
|-------------|--------------|
| `knowledge_core` | quiz, exam, notes, slides, flashcards |
| `quiz` | flashcards |

All other generation paths are **ILLEGAL** and will return 400.

---

## Error Handling (Frontend)

```typescript
try {
  const jobId = await createJob(...);
  const result = await pollUntilComplete(jobId);
} catch (err) {
  if (err.message.includes('400')) {
    // Bad request - show field-level validation error
  } else if (err.message.includes('Job failed')) {
    // Backend processing failed - show error_message
  } else {
    // Network/server error - show retry option
  }
}
```

---

## Starting the Backend

```bash
# Terminal 1: API server
cd /Users/vishnu/Documents/beeprepared
source backend/venv/bin/activate
uvicorn backend.api:app --reload --port 8000

# Terminal 2: Job runner
cd /Users/vishnu/Documents/beeprepared
source backend/venv/bin/activate
PYTHONPATH=. python backend/job_runner.py
```

Both must be running.

