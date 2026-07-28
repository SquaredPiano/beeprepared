# Setup guide

Getting BeePrepared running, and what to check when it does not.

---

## Prerequisites

| | Why | Check |
|---|---|---|
| **Git** | To clone the repository | `git --version` |
| **Docker Desktop** | Bundles Python, Node, FFmpeg and LaTeX | `docker --version` |

Docker is the recommended path because the backend needs FFmpeg for audio and a
LaTeX distribution for exam PDFs. A native setup is documented at the end.

---

## Quick start

```bash
git clone https://github.com/SquaredPiano/beeprepared.git
cd beeprepared
cp .env.example .env
docker compose up
```

Open **[localhost:3000](http://localhost:3000)**.

That is two containers: the backend and the frontend. The API runs its own
worker pool and an in-process event bus, so there is no broker and no database
server to stand up.

### Running the distributed shape

The same code can run as three processes instead of one, with Redis carrying
both the job queue and the event stream between an API and separate Celery
workers. Add the overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.celery.yml up
```

Nothing about the image or the code changes. Which shape you get is decided by
`CELERY_ENABLED` and `REDIS_URL`, and by nothing else — `/health` will report
`events: redis` and `jobs: celery` instead of `memory` and `local`.

Do not run `docker compose up api` on its own under the overlay. `api` there is
the Celery half of the stack: it hands work to the broker and starts no worker,
so without the `worker` service every job is accepted and then never runs.

### Do I need to configure anything?

One value, and only for quality. Everything else has a working default:

| | Default |
|---|---|
| Database | SQLite on a Docker volume, durable across restarts |
| File storage | The same volume, served through signed links |
| Queue | The API's own in-process worker pool |
| Signing key | Minted per install and persisted on the volume |
| Model | A local heuristic engine |

Set `OPENROUTER_API_KEY` in `.env` to switch generation from the heuristic
engine to a real model. Get one at
[openrouter.ai/keys](https://openrouter.ai/keys):

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

The same key also transcribes audio and video, so there is nothing else to sign
up for. Without it, PDFs, slide decks and Markdown still work; recordings do
not, because there is no model to listen to them.

---

## What "working" looks like

The API logs what it resolved at startup:

```log
beeprepared-api  | BeePrepared starting
beeprepared-api  |   database : /data/beeprepared.db
beeprepared-api  |   files    : /data/files
beeprepared-api  |   events   : memory
beeprepared-api  |   jobs     : local
beeprepared-api  |   model    : openrouter
beeprepared-api  | INFO:     Application startup complete.
```

Under the Celery overlay the last two read `events : redis` and `jobs : celery`.
If they say `local` while you expected `celery`, the API did not reach the
broker and is quietly doing the work itself.

The same information is on `/health`:

```bash
curl localhost:8000/health
```

Read that first whenever something behaves unexpectedly — most confusing
failures come from being connected to something other than what you assumed.

Then walk the happy path:

1. Open [localhost:3000](http://localhost:3000) and create a project.
2. Drag a PDF, a recording or a Markdown file onto the canvas.
3. Watch the node move through *storing → reading → cleaning → building
   knowledge core*. Those updates arrive over a WebSocket.
4. Drag a **Quiz** node from the sidebar and connect the core to it.
5. Press **Run**. The button says how many steps it is about to execute.

---

## Troubleshooting

**`model: offline` in the logs, and artifacts read like word salad.**
No key was picked up. Check `OPENROUTER_API_KEY` in the `.env` at the repository
root, then `docker compose up -d --force-recreate api worker`.

**Uploading a recording fails with "transcription needs a language model".**
Same cause: audio goes through the model, and the offline engine cannot listen.

**Nodes never leave "pending".**
Nothing is draining the queue. On the default stack that should be impossible,
because the API is the worker — check `/health` says `jobs: local`. Under the
Celery overlay, check `docker compose ps worker`. Jobs are not lost while a
worker is down: the row is written before anything is dispatched, and beat
re-dispatches pending work every two minutes.

**Progress never updates, but artifacts eventually appear.**
The WebSocket is not connecting; the canvas shows *"Live updates offline"*.
Usually a proxy stripping the `Upgrade` header. Confirm
`NEXT_PUBLIC_BACKEND_URL` points at the API directly.

**"This flow cannot run".**
The graph did not compile. Hover the Run button — the message names the node.
Usually a generator with nothing connected, or a cycle.

**Exam PDFs are missing though the exam generated.**
`pdflatex` is not on the path. The image installs TeX Live; a native setup may
not have it. The exam is still valid — exporting is a convenience and never
fails a job.

**Reset everything.**
```bash
docker compose down -v
```

---

## Running natively

```bash
python -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

With no `REDIS_URL`, the API runs its own worker pool — same code path, one
fewer moving part. To use Celery instead:

```bash
celery -A backend.celery_app:celery_app worker --loglevel=info
celery -A backend.celery_app:celery_app beat   --loglevel=info
```

```bash
cd frontend && npm install && npm run dev
```

```bash
backend/venv/bin/python -m pytest -q -p no:warnings
```

Invoke the virtualenv's Python explicitly. A bare `pytest` or `python3` will
pick up the system interpreter, which does not have the dependencies.

The tests need no network and no key: they run the real handlers against a
temporary database and the offline model.

System dependencies for a native backend: `ffmpeg`, and a TeX distribution such
as `mactex` or `texlive-latex-extra` if you want exam PDFs.
