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

Upload a lecture — a recording, a slide deck, a PDF, a YouTube link — and
BeePrepared distils it into a **knowledge core**: one structured representation
of what the material actually says. Everything else is generated from that core,
which is why the quiz, the notes and the exam agree with each other instead of
each hallucinating separately.

The interesting part sits on top: an **infinite canvas where the graph you draw
is the program that runs**.

```
   lecture.mp4 ─┐
                ├─→ [ Notes ] ─┬─→ [ Mind map ]
   textbook.pdf ─┘             └─→ [ Cheat sheet ]

   [ Quiz ] ─┬─→ [ Flashcards ]
             └─→ [ Mock exam ]
```

Nodes take **multiple inputs** (three lectures merge into one set of notes) and
feed **multiple outputs** (one quiz becomes flashcards *and* an exam *and* a
cheat sheet). Press Run and the backend topologically sorts the graph, runs
every independent branch concurrently, and streams each node's progress over a
WebSocket.

<div align="center">
  <img src="frontend/public/gallery.jpg" alt="BeePrepared canvas" width="100%" style="border-radius: 8px; border: 1px solid #333;"/>
</div>

---

## Features

| | |
|---|---|
| **Knowledge core** | Source material is distilled once. Every artifact derives from it, so they stay consistent |
| **Executable canvas** | The node graph compiles to a DAG, is validated, and runs wave by wave |
| **Multi-input merge** | Several sources are map/reduced into one context — contradictions are *labelled*, not silently resolved |
| **Eight artifact types** | Notes, quiz, flashcards, slides, mock exam, study guide, cheat sheet, mind map |
| **Steerable generation** | An assistant takes plain English — "make these harder", "focus on chapter 3" — and rebuilds the artifact |
| **Live progress** | One WebSocket per project. No polling |
| **Universal ingest** | MP4, MP3, PDF, PPTX, Markdown, YouTube. Recordings are transcribed on the way in |
| **Real exports** | Exams typeset to PDF via LaTeX, decks to PPTX, notes to Markdown |

---

## Running it

```bash
git clone https://github.com/SquaredPiano/beeprepared.git
cd beeprepared
cp .env.example .env      # add OPENROUTER_API_KEY for real generations
docker compose up
```

Open [localhost:3000](http://localhost:3000).
[localhost:8000/health](http://localhost:8000/health) reports exactly what the
backend connected itself to.

**Without Docker:**

```bash
python -m venv backend/venv && source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload

cd frontend && npm install && npm run dev
```

### No accounts, no cloud services

State lives in an embedded SQLite file and a local directory. There is no
database to provision, no object store to configure and no auth provider to
register with — clone the repository and it runs.

One key is worth setting: `OPENROUTER_API_KEY`. It covers **both** generation
and audio transcription, so there is no second vendor. Without it the backend
falls back to a local heuristic engine that still runs the whole pipeline, just
with much duller output — which is also what lets the test suite exercise the
real code paths with no network.

Redis is optional, and `docker compose up` does without it: the API runs its own
worker pool and an in-process event bus, so the default install is two
containers and no broker.

To run the distributed shape instead — an API, separate Celery workers, and
Redis carrying both the queue and the event stream between them — add the
overlay, and scale the workers if you want to watch them share the queue:

```bash
docker compose -f docker-compose.yml -f docker-compose.celery.yml up
docker compose -f docker-compose.yml -f docker-compose.celery.yml up --scale worker=3
```

Same image, same code path. `CELERY_ENABLED` and `REDIS_URL` decide which shape
you get, and `/health` tells you which one you actually got.

---

## How it works

```
Upload ──▶ Normalise ──▶ Extract ──▶ Clean ──▶ Knowledge core
                                                     │
                     ┌───────────────────────────────┘
                     ▼
     Flow engine: compile canvas ──▶ validate ──▶ schedule waves
                     │
                     ▼
     Job queue ──▶ Worker ──▶ Generate ──▶ Export ──▶ Commit
                     │                                  │
                     └──── progress ──▶ WebSocket ◀─────┘
```

The reasoning behind each design decision is in
**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.

| Package | Responsibility |
|---|---|
| `api/` | HTTP and WebSocket surface, one route module per resource |
| `handlers/` | One class per job type. Pure: they return work, never write it |
| `pipeline/` | Source to knowledge core: ingestion, extraction, media, cleaning |
| `services/` | Persistence, files, events, queueing, generation, flow execution |
| `llm/` | Model providers behind one interface |
| `models/` | The domain vocabulary every layer shares |

### Decisions worth calling out

**Handlers never write to the database.** A handler returns a `JobBundle`; the
runner commits it in one transaction. A job that fails halfway cannot leave a
half-written knowledge graph.

**The queue is a table, not a message.** The row is committed before dispatch,
so a broker outage delays work rather than losing it. `claim_job` is atomic, so
workers racing on one queue never double-run a job, and a reaper returns jobs
stranded by a crashed worker.

**Failures are classified before they are recorded.** A rate limit is transient
and requeued; a malformed payload is permanent and retrying it would only burn
tokens.

**Provenance is a DAG, not a tree.** An artifact generated from three sources
gets three `derived_from` edges, and cycles are rejected at compile time.

---

## Testing

```bash
pytest -q                        # 108 tests, no network, no API keys
```

- `test_flow_engine.py` — compilation, fan-in, fan-out, cycle detection, waves
- `test_pipeline.py` — every artifact type end to end, chaining, refinement,
  retry classification, racing workers partitioning one queue, stale-job reaping
- `test_api.py` — HTTP contract, ownership, upload limits, WebSocket lifecycle,
  signed-link verification
- `test_seams.py` — the abstraction boundaries, driven through fakes: a
  substitute provider standing in for OpenRouter, and a handler running against
  an injected generator

---

## Stack

**Frontend** — Next.js 16 (App Router), React 19, React Flow, Zustand, Tailwind 4
**Backend** — FastAPI, Pydantic v2, Celery, Redis, SQLite
**Model** — OpenRouter, for both generation and transcription
**Exports** — LaTeX → PDF, python-pptx → PPTX, FFmpeg for media

---

<div align="center">
  <sub>SquaredPiano × BeePrepared</sub>
</div>
