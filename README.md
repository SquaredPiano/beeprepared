<div align="center">
  <img src="frontend/public/logo.png" alt="BeePrepared Logo" width="120" style="margin-bottom: 20px;"/>
  
  # BeePrepared
  
  **Transform lectures into study materials in under three minutes**
  
  [![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js)](https://nextjs.org/)
  [![React](https://img.shields.io/badge/React-19-blue?style=for-the-badge&logo=react)](https://react.dev/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
  [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-3ECF8E?style=for-the-badge&logo=postgresql)](https://supabase.com/)
  
  [Demo Video](https://www.youtube.com/watch?v=S2ZwaheHSiY) · [Devpost](https://devpost.com/software/beeprepared) · [Report Bug](https://github.com/SquaredPiano/beeprepared/issues)
</div>

---

## 🎬 Demo

<div align="center">
  <video src="https://www.youtube.com/watch?v=VUVFwkcULzk" controls width="100%" poster="frontend/public/gallery.jpg">
    <a href="https://www.youtube.com/watch?v=VUVFwkcULzk">Watch local demo video</a>
  </video>
  <p><em>Turn a 2-hour lecture into a complete study pack in seconds.</em></p>
</div>

---

## ✨ Overview

BeePrepared is an **AI-native learning platform** that ingests raw lecture content and outputs structured study artifacts. It uses a graph-based "Knowledge Core" to ensure consistency across generated materials.

> *"Upload a lecture, get a study guide."* — Simple as that.

<div align="center">
  <img src="frontend/public/gallery.jpg" alt="BeePrepared Dashboard" width="100%" style="border-radius: 8px; border: 1px solid #333;"/>
</div>

### Features

| Feature | Description |
|---------|-------------|
| 🧠 **Knowledge Core** | AI extracts concepts and relationships into a graph, acting as a single source of truth. |
| 📹 **Universal Ingest** | Upload MP4, MP3, PDF, PPTX, or YouTube URLs. We handle the transcription and OCR. |
| 🎨 **Canvas Workflow** | Infinite canvas to organize, connect, and generate study nodes (Quizzes, Flashcards, Notes). |
| ⚡ **Deepgram Nova-2** | Lightning-fast transcription with high accuracy for technical terms. |
| 🔄 **Node Chaining** | Generate artifacts from other artifacts (e.g., Flashcards *derived from* a Quiz). |

---

## 📸 Gallery

<div align="center" style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
  <img src="frontend/public/canvas-demo.png" alt="Canvas Interface" width="48%" style="border-radius: 6px;"/>
  <img src="frontend/public/dashboard-demo.png" alt="Project Dashboard" width="48%" style="border-radius: 6px;"/>
  <img src="frontend/public/ingest-demo.png" alt="Ingestion Process" width="48%" style="border-radius: 6px;"/>
  <img src="frontend/public/database-demo.png" alt="Database Schema" width="48%" style="border-radius: 6px;"/>
</div>

---

## 🚀 Local Setup

### Prerequisites

- **Python** 3.10+
- **Node.js** 20+
- **FFmpeg** (Required for audio processing)
- **Supabase** Project

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate
pip install -r requirements.txt
```

**`.env` Configuration:**
```env
# Core Services
GEMINI_API_KEY=your_gemini_key
DEEPGRAM_API_KEY=your_deepgram_key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key

# Database (Direct Connection)
DATABASE_URL=postgresql://postgres:password@db.project.supabase.co:5432/postgres

# Object Storage (Cloudflare R2)
R2_ACCOUNT_ID=your_id
R2_ACCESS_KEY_ID=your_key
R2_SECRET_ACCESS_KEY=your_secret
R2_BUCKET_NAME=beeprepared-storage
R2_ENDPOINT_URL=https://{id}.r2.cloudflarestorage.com
```

**Run Server:**
```bash
python -m uvicorn main:app --reload --port 8000
```

### 2. Database

Execute the content of [`backend/schema.sql`](./backend/schema.sql) in your Supabase SQL Editor to set up the schema, RPC functions, and triggers.

### 3. Frontend

```bash
cd frontend
npm install
```

**`.env.local` Configuration:**
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

**Run Client:**
```bash
npm run dev
```

Visit [http://localhost:3000](http://localhost:3000).

---

## 🛠️ Architecture

BPP (BeePrepared Platform) uses a **Generator-Node** architecture.

```
[Ingest] -> [Transcription] -> [Knowledge Core Extraction]
                                        ↓
[Canvas UI] -> [Node Graph] -> [Artifact Generation (LLM)]
```

- **Frontend**: Next.js 16 (App Router), React Flow, Tailwind 4, Zustand.
- **Backend**: FastAPI, Pydantic, Supabase (pgvector + jsonb).
- **AI**: Gemini 2.5 Pro (Reasoning), Deepgram Nova-2 (Audio).

---

## 🤝 Contributing

We welcome contributions! Please fork the repo and submit a PR.

---

<div align="center">
  <sub>SquaredPiano × BeePrepared</sub>
</div>
