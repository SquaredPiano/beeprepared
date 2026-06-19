# Setup guide

Getting BeePrepared running, and what to check when it does not.

---

## Prerequisites

| | Why | Check |
|---|---|---|
| **Git** | To clone the repository | `git --version` |
| **Docker Desktop** | Bundles Python, Node, FFmpeg and LaTeX | `docker --version` |

Docker is the recommended path because the backend needs FFmpeg for media and a
LaTeX distribution for exam PDFs, and installing those on a host machine is more
trouble than it is worth. A native setup is documented at the end.

---

## Quick start

```bash
git clone https://github.com/SquaredPiano/beeprepared.git
cd beeprepared
cp .env.example .env
docker compose up
```

Open **[localhost:3000](http://localhost:3000)**.

### Do I need to configure anything?

No. Every external dependency has a local fallback, so the stack comes up with
an empty `.env`:

| | What you get by default |
|---|---|
| Database | Embedded SQLite on a Docker volume. Durable across restarts |
| Storage | Files on the same volume, served through signed URLs |
| Queue | Redis + Celery, started by compose |
| Model | An offline heuristic engine |

The one value worth setting is `OPENROUTER_API_KEY` — that switches generation
from the offline engine to a real model. Get one at
[openrouter.ai/keys](https://openrouter.ai/keys) and put it in `.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Audio and video sources also need `DEEPGRAM_API_KEY` for transcription. PDFs,
slide decks, Markdown and YouTube work without it.

---

## What "working" looks like

The API logs what it actually connected itself to at startup:

```log
beeprepared-api  | BeePrepared API starting
beeprepared-api  |   database : local (SUPABASE_URL/SUPABASE_KEY not configured)
beeprepared-api  |   storage  : local
beeprepared-api  |   events   : redis
beeprepared-api  |   jobs     : celery
beeprepared-api  |   llm      : OpenRouterLLM
beeprepared-api  | INFO:     Application startup complete.
```

The same information is on `/health`:

```bash
curl localhost:8000/health
# {"status":"healthy","database":"local","storage":"local","events":"redis","jobs":"celery"}
```

Read those two lines first whenever something behaves unexpectedly. Most
confusing failures in this system come from being connected to something other
than what you assumed.

Then walk the happy path:

1. Open [localhost:3000](http://localhost:3000) and create a project.
2. Drag a PDF or Markdown file onto the canvas.
3. Watch the ingest node move through *storing → extracting → cleaning →
   building knowledge core*. Those updates arrive over a WebSocket; if the node
   never moves, see the troubleshooting section.
4. Drag a **Quiz** node from the sidebar and connect the core to it.
5. Press **Run**. The button tells you how many steps it is about to execute.

---

## Troubleshooting

**`llm: OfflineLLM` in the logs, and artifacts read like word salad.**
No model key was picked up. Check `OPENROUTER_API_KEY` is set in the `.env` at
the repository root (not `backend/.env`), then restart:
`docker compose up -d --force-recreate api worker`.

**Nodes never leave "pending".**
Nothing is draining the queue. Check the worker is up (`docker compose ps
worker`) and that it can reach Redis. Jobs are not lost while a worker is down -
the beat service re-dispatches anything pending every two minutes.

**Progress never updates, but artifacts eventually appear.**
The WebSocket is not connecting. The canvas shows *"Live updates offline"* when
this happens. Usually a proxy stripping the `Upgrade` header; confirm
`NEXT_PUBLIC_BACKEND_URL` points at the API directly.

**"This flow cannot run".**
The graph did not compile. Hover the Run button - the message names the node.
Usually a generator with nothing connected to its input, or a cycle.

**Exam PDFs are missing while the exam itself generated fine.**
`pdflatex` is not on the path. The image installs TeX Live; a native setup may
not have it. The exam artifact is still valid - rendering is a convenience and
never fails a job.

**Reset everything.**
```bash
docker compose down -v      # -v drops the volume: database and artifacts
```

---

## Running natively

```bash
# Backend
python -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

With no `REDIS_URL` set, the API runs its own in-process worker pool - same code
path, one fewer moving part. To run Celery instead:

```bash
celery -A backend.celery_app:celery_app worker --loglevel=info
celery -A backend.celery_app:celery_app beat   --loglevel=info
```

```bash
# Frontend
cd frontend && npm install && npm run dev
```

```bash
# Tests - no network, no API keys
pytest backend/tests -q
```

System dependencies for a native backend: `ffmpeg` (media) and a TeX
distribution such as `mactex` or `texlive-latex-extra` (exam PDFs).

---

## Using hosted infrastructure instead

Every seam swaps by setting environment variables. Nothing else changes.

```bash
# Postgres via Supabase
DATABASE_BACKEND=supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=<service role key>
# then apply backend/schema.sql in the SQL editor

# Cloudflare R2 for artifacts
STORAGE_BACKEND=r2
R2_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=beeprepared
```

Set `DATABASE_BACKEND=auto` / `STORAGE_BACKEND=auto` to use the hosted service
when it is reachable and fall back to local when it is not.
