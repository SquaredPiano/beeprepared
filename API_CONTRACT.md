# BeePrepared API Contract

**Status:** FROZEN  
**Base URL:** `http://localhost:8000`

---

## Endpoints

### 1. Create Job

```http
POST /api/jobs
Content-Type: application/json
```

**Request:**
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

**Or for generate:**
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

---

## Starting the Backend

```bash
# Terminal 1: API server
cd backend
source venv/bin/activate
uvicorn api:app --reload --port 8000

# Terminal 2: Job runner
cd backend  
source venv/bin/activate
python job_runner.py
```

Both must be running.
