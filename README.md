<div align="center">
  <img src="frontend/public/logo.png" alt="BeePrepared Logo" width="120" style="margin-bottom: 20px;"/>

  # BeePrepared

  **Wire your lecture material into a pipeline. Get a study pack out the other end.**

  [![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js)](https://nextjs.org/)
  [![React](https://img.shields.io/badge/React-19-blue?style=for-the-badge&logo=react)](https://react.dev/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
  [![Celery](https://img.shields.io/badge/Celery-Redis-37814A?style=for-the-badge&logo=celery)](https://docs.celeryq.dev/)

  [Demo Video](https://www.youtube.com/watch?v=S2ZwaheHSiY) · [Devpost](https://devpost.com/software/beeprepared) · [Report a bug](https://github.com/SquaredPiano/beeprepared/issues)
</div>

---

## What it is

Upload a lecture - a recording, a slide deck, a PDF, a YouTube link - and BeePrepared
distils it into a **Knowledge Core**: one structured representation of what the material
actually says. Everything else is generated from that core, which is why the quiz, the
notes and the exam agree with each other instead of each hallucinating separately.

The interesting part is what sits on top: an **infinite canvas where the graph you draw
is the program that runs**.

```
   lecture.mp4 ─┐
                ├─→ [ Notes ] ─┬─→ [ Mind map ]
   textbook.pdf ─┘             └─→ [ Cheat sheet ]

   [ Quiz ] ─┬─→ [ Flashcards ]
             └─→ [ Mock exam ]
```

Nodes take **multiple inputs** (three lectures merge into one set of notes) and feed
**multiple outputs** (one quiz becomes flashcards *and* an exam *and* a cheat sheet).
Press Run, and the backend topologically sorts the graph, runs every independent branch
concurrently, and streams each node's progress back over a WebSocket.

<div align="center">
  <img src="frontend/public/gallery.jpg" alt="BeePrepared canvas" width="100%" style="border-radius: 8px; border: 1px solid #333;"/>
</div>

---

## Features

| | |
|---|---|
| **Knowledge Core** | Source material is distilled once into a structured core. Every artifact derives from it, so they stay consistent with each other. |
| **Executable canvas** | The node graph is compiled into a DAG, validated (cycles, orphans, bad type transitions), and executed wave by wave. |
| **Multi-input merge** | Several sources feeding one node are map/reduced into a single context - contradictions between sources are *labelled*, not silently resolved. |
| **Eight artifact types** | Notes, quiz, flashcards, slides, mock exam, study guide, cheat sheet, mind map. |
| **Steerable generation** | An assistant panel takes plain English - "make these harder", "focus on chapter 3" - and rebuilds the artifact instead of re-rolling it. |
| **Live progress** | One WebSocket per project. No polling. |
| **Universal ingest** | MP4, MP3, PDF, PPTX, Markdown, YouTube. Audio is normalised and transcribed on the way in. |
| **Real exports** | Exams typeset to PDF via LaTeX, decks to PPTX, notes to Markdown. |

---

## Running it

**One command, no accounts, no cloud services:**

```bash
git clone https://github.com/SquaredPiano/beeprepared.git
cd beeprepared
cp .env.example .env      # optional: add OPENROUTER_API_KEY for real generations
docker compose up
```

Then open [localhost:3000](http://localhost:3000). [localhost:8000/health](http://localhost:8000/health)
will tell you exactly what the backend connected itself to.

**Without Docker:**

```bash
# Backend - API and an in-process worker pool
python -m venv backend/venv && source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

### Configuration is optional, everywhere

Every external dependency has a working local fallback, and the backend picks whichever
is actually configured and reachable at startup:

| | Default | Upgrade to |
|---|---|---|
| **Database** | Embedded SQLite - durable, transactional, zero setup | Supabase / Postgres (`SUPABASE_URL`) |
| **Storage** | Local disk, served through signed URLs | Cloudflare R2 (`R2_*`) |
| **Queue** | In-process asyncio worker pool | Celery over Redis (`REDIS_URL`) |
| **Model** | Offline heuristic engine | Any model via OpenRouter (`OPENROUTER_API_KEY`) |

This is deliberate. Personal projects rot when a free tier expires or a key gets rotated;
the point here is that a dead credential degrades one dimension of quality instead of
taking the product down. The offline engine still runs the *entire* pipeline - ingest,
extraction, DAG execution, rendering - which is also what lets the test suite exercise
the real code paths without a network.

---

## How it works

```
Upload ──▶ Normalise ──▶ Extract text ──▶ Clean ──▶ Knowledge Core
                                                          │
                        ┌─────────────────────────────────┘
                        ▼
        Flow engine: compile canvas ──▶ validate ──▶ schedule waves
                        │
                        ▼
        Job queue ──▶ Worker ──▶ Generate ──▶ Render ──▶ Commit
                        │                                   │
                        └──── progress ──▶ WebSocket ◀──────┘
```

Design decisions and the reasoning behind them are written up in
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

### The pieces

| Layer | What it does |
|---|---|
| `api/routes/` | HTTP and WebSocket surface. One module per resource. |
| `services/flow_engine.py` | Compiles the canvas into a validated DAG and schedules it wave by wave. |
| `services/job_runner.py` | Owns the transaction boundary: claim → run → commit → notify. |
| `handlers/` | The actual work. Pure functions from a job to a bundle; they never touch the database. |
| `services/db_interface.py` | One seam over SQLite or Supabase. |
| `services/storage.py` | One seam over local disk or R2. |
| `core/services/llm_*.py` | One seam over OpenRouter, Gemini, Vertex, or the offline engine. |

### Design decisions worth calling out

**Handlers never write to the database.** A handler returns a `JobBundle` describing
everything it produced; the runner commits it in a single transaction. A job that fails
halfway cannot leave a half-written knowledge graph behind.

**The job queue is a table, not a message.** A job row is committed before it is
dispatched, so a broker outage delays work rather than losing it - a periodic drain task
picks up anything that was never enqueued, and a reaper returns jobs stranded by a
crashed worker. `claim_job` is atomic (`BEGIN IMMEDIATE` on SQLite, `FOR UPDATE SKIP
LOCKED` on Postgres), so workers racing on the same queue never double-run a job.

**Failures are classified before they are recorded.** A rate limit is transient and the
job goes back on the queue; a malformed payload is permanent and retrying it would only
burn tokens.

**Provenance is a DAG, not a tree.** An artifact generated from three sources gets three
`derived_from` edges. Cycles are rejected at compile time and again by a database
trigger.

---

## Testing

```bash
pytest backend/tests -q          # 86 tests, no network, no API keys
```

The suite runs against a temporary SQLite database and the offline model, so it covers
the real handlers, real transactions and real DAG traversal rather than mocks:

- `test_flow_engine.py` - compilation, fan-in, fan-out, cycle detection, wave scheduling
- `test_pipeline.py` - every artifact type end to end, chaining, refinement, retry
  classification, atomic claim, stale-job reaping
- `test_api.py` - HTTP contract, ownership rules, upload limits, WebSocket lifecycle,
  signed-URL verification

---

## Stack

**Frontend** — Next.js 16 (App Router), React 19, React Flow, Zustand, Tailwind 4, Framer Motion
**Backend** — FastAPI, Pydantic v2, Celery, Redis, SQLite / Postgres
**AI** — OpenRouter (any model), Deepgram for transcription
**Rendering** — LaTeX → PDF, python-pptx → PPTX, FFmpeg for media

---

<div align="center">
  <sub>SquaredPiano × BeePrepared</sub>
</div>
