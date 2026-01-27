<div align="center">
  <img src="./frontend/public/logo.png" alt="BeePrepared Logo" width="120"/>
  
  # BeePrepared 🐝
  
  **Transform lectures into study materials in under three minutes**
  
  [![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js)](https://nextjs.org/)
  [![React](https://img.shields.io/badge/React-19-blue?style=for-the-badge&logo=react)](https://react.dev/)
  [![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
  [![TypeScript](https://img.shields.io/badge/TypeScript-5-blue?style=for-the-badge&logo=typescript)](https://www.typescriptlang.org/)
  [![Python](https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge&logo=python)](https://python.org/)
  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)
  
  [📺 Demo Video (5 min)](https://www.youtube.com/watch?v=S2ZwaheHSiY) · [⚡ Quick Demo (1:42)](https://youtu.be/VUVFwkcULzk) · [🏆 Devpost](https://devpost.com/software/beeprepared) · [💻 GitHub](https://github.com/SquaredPiano/beeprepared)
</div>

---

## 🎬 Demo

<div align="center">
  <a href="https://www.youtube.com/watch?v=S2ZwaheHSiY">
    <img src="https://img.shields.io/badge/▶️_Watch_Full_Demo_(5_min)-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="Watch Demo Video"/>
  </a>
  <a href="https://youtu.be/VUVFwkcULzk">
    <img src="https://img.shields.io/badge/▶️_Quick_Demo_(1:42)-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="Watch Quick Demo"/>
  </a>
</div>

---

## 🌟 Overview

BeePrepared is an **AI-powered educational platform** that transforms lecture recordings, documents, and slides into comprehensive study materials. Upload any lecture format and receive notes, flashcards, practice exams, and audio guides—all generated in under three minutes.

> *Upload a 60-minute lecture video → Get study notes, 20 flashcards, a practice exam, and presentation slides* — Done.

### ✨ Why BeePrepared?

| Feature | Description |
|---------|-------------|
| 📹 **Multi-Format Ingestion** | Upload video (MP4, MOV), audio (MP3, WAV), PDFs, PowerPoint, or plain text |
| 🧠 **Knowledge Core Extraction** | AI extracts concepts, relationships, and key facts into a structured graph |
| 🎨 **Visual Canvas Workflow** | Drag-and-drop interface with React Flow for intuitive artifact generation |
| 📝 **5 Study Artifacts** | Study Notes, Flashcards, Practice Quizzes, Mock Exams, and Presentation Slides |
| ⚡ **Parallel Processing** | Generate all artifacts simultaneously in under 3 minutes |
| 🎯 **Chain Artifacts** | Generate flashcards from a quiz, or notes from an exam—full DAG support |

---

## 🚀 Quick Start

### Prerequisites

Before running BeePrepared, install:

| Dependency | Version | Installation |
|------------|---------|--------------|
| **Python** | 3.11+ | [python.org](https://python.org) |
| **Node.js** | 20+ | [nodejs.org](https://nodejs.org) |
| **FFmpeg** | Latest | `brew install ffmpeg` (macOS) or [ffmpeg.org](https://ffmpeg.org) |

### Required API Keys

| Service | Purpose | Get Key |
|---------|---------|---------|
| **Supabase** | Database & Auth | [supabase.com](https://supabase.com) |
| **Google Gemini** | AI/LLM for extraction | [ai.google.dev](https://ai.google.dev) |
| **Azure Speech** | Audio transcription | [azure.microsoft.com](https://azure.microsoft.com/en-us/products/cognitive-services/speech-services/) |
| **Cloudflare R2** | Object storage | [cloudflare.com/r2](https://www.cloudflare.com/products/r2/) |

---

## 🛠️ Installation

### 1. Clone the Repository

```bash
git clone https://github.com/SquaredPiano/beeprepared.git
cd beeprepared
```

### 2. Backend Setup

```bash
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

**Configure environment variables:**

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# Cloudflare R2 (Object Storage)
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=beeprepared-storage
R2_ENDPOINT_URL=https://{account_id}.r2.cloudflarestorage.com

# Google Gemini (AI/LLM)
GEMINI_API_KEY=your_gemini_key

# Supabase (Database & Auth)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_service_role_key
DATABASE_URL=postgresql://postgres:password@db.your-project.supabase.co:5432/postgres

# Azure Speech (Transcription)
AZURE_SPEECH_KEY=your_key
AZURE_SPEECH_REGION=eastus

# Server Config
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:3000
```

**Start the backend:**

```bash
uvicorn main:app --reload --port 8000
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install
```

**Configure environment variables:**

Create `.env.local`:

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_public_key
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

**Start the frontend:**

```bash
npm run dev
```

### 4. Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

---

## 🎮 Usage

### Canvas Workflow

1. **Upload Source** → Drag a video, audio, or document into the canvas
2. **Wait for Ingestion** → The "Forager Bee" processes your file and creates a Knowledge Core
3. **Add Generators** → Drag Quiz, Notes, Flashcards, Exam, or Slides nodes from the sidebar
4. **Connect & Generate** → Link nodes with edges and click Generate
5. **Chain Artifacts** → Connect a Flashcards node to a Quiz node to generate flashcards from quiz content

### Supported Formats

| Category | Formats |
|----------|---------|
| **Audio** | MP3, WAV, M4A, OGG, FLAC |
| **Video** | MP4, MOV, AVI, WebM, MKV |
| **Documents** | PDF, PPTX |
| **Text** | MD, TXT |

---

## 🏗️ Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   Canvas    │  │  Generator  │  │   Artifact  │  │   Polling   │    │
│  │   (React    │→ │    Nodes    │→ │   Preview   │← │   System    │    │
│  │    Flow)    │  │             │  │    Modal    │  │  (5s loop)  │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTP (REST)
┌────────────────────────────────▼────────────────────────────────────────┐
│                              BACKEND                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  FastAPI    │  │   Ingest    │  │  Generate   │  │   Binary    │    │
│  │  Router     │→ │   Handler   │→ │   Handler   │→ │  Renderer   │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
│                          │                │                │            │
│                          ▼                ▼                ▼            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │   Azure     │  │   Gemini    │  │  Knowledge  │  │   PyLaTeX   │    │
│  │   Speech    │  │   2.5 Pro   │  │    Core     │  │   python-   │    │
│  │             │  │             │  │   Builder   │  │    pptx     │    │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────┐
│                          DATA LAYER                                      │
│  ┌─────────────────────┐           ┌─────────────────────┐              │
│  │      Supabase       │           │    Cloudflare R2    │              │
│  │   (PostgreSQL +     │           │   (Object Storage)  │              │
│  │    Auth + RLS)      │           │                     │              │
│  └─────────────────────┘           └─────────────────────┘              │
└─────────────────────────────────────────────────────────────────────────┘
```

### Processing Pipeline

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Upload  │ →  │ Transcr. │ →  │ Extract  │ →  │ Generate │
│  (R2)    │    │ (Azure)  │    │ (Gemini) │    │ (Gemini) │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │               │               │
     ▼               ▼               ▼               ▼
   Video          Flat Text      Knowledge        Artifacts
   stored         transcript       Core          (Quiz, Notes,
                                                 Flashcards...)
```

---

## 🛠️ Tech Stack

<div align="center">

### Frontend
![Next.js](https://img.shields.io/badge/Next.js-16-black?style=for-the-badge&logo=next.js)
![React](https://img.shields.io/badge/React-19-blue?style=for-the-badge&logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-5-blue?style=for-the-badge&logo=typescript)
![Tailwind](https://img.shields.io/badge/Tailwind-4-38bdf8?style=for-the-badge&logo=tailwind-css)
![React Flow](https://img.shields.io/badge/React_Flow-12-purple?style=for-the-badge)

### Backend
![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?style=for-the-badge&logo=fastapi)
![Python](https://img.shields.io/badge/Python-3.11+-yellow?style=for-the-badge&logo=python)
![Pydantic](https://img.shields.io/badge/Pydantic-2.12-red?style=for-the-badge)

### AI & Services
![Gemini](https://img.shields.io/badge/Gemini-2.5_Pro-4285F4?style=for-the-badge&logo=google)
![Azure](https://img.shields.io/badge/Azure_Speech-0078D4?style=for-the-badge&logo=microsoft-azure)

### Infrastructure
![Supabase](https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white)
![Cloudflare](https://img.shields.io/badge/Cloudflare_R2-F38020?style=for-the-badge&logo=cloudflare&logoColor=white)

</div>

### Full Dependency List

<details>
<summary><strong>Frontend Dependencies</strong></summary>

| Package | Version | Purpose |
|---------|---------|---------|
| `next` | 16.1.4 | React framework |
| `react` | 19.2.3 | UI library |
| `@xyflow/react` | 12.10.0 | Visual canvas |
| `zustand` | 5.0.10 | State management |
| `@tanstack/react-query` | 5.90.20 | Data fetching |
| `framer-motion` | 12.29.0 | Animations |
| `gsap` | 3.14.2 | Complex animations |
| `@supabase/supabase-js` | 2.91.1 | Auth & database |
| `react-markdown` | 9.0.1 | Markdown rendering |
| `katex` | 0.16.11 | LaTeX math rendering |
| `sonner` | 2.0.7 | Toast notifications |
| `lucide-react` | 0.563.0 | Icons |

</details>

<details>
<summary><strong>Backend Dependencies</strong></summary>

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | 0.128.0 | API framework |
| `uvicorn` | 0.40.0 | ASGI server |
| `pydantic` | 2.12.5 | Data validation |
| `supabase` | 2.27.2 | Database client |
| `google-genai` | 1.60.0 | Gemini AI |
| `azure-cognitiveservices-speech` | 1.47.0 | Transcription |
| `boto3` | 1.42.34 | S3/R2 client |
| `PyMuPDF` | 1.26.7 | PDF processing |
| `python-pptx` | 1.0.2 | PowerPoint processing |
| `PyLaTeX` | 1.4.2 | PDF generation |
| `ffmpeg-python` | 0.2.0 | Video processing |
| `httpx` | 0.28.1 | Async HTTP |

</details>

---

## 📁 Project Structure

```
beeprepared/
├── backend/
│   ├── main.py                    # FastAPI application entry
│   ├── handlers/
│   │   ├── ingest_handler.py      # File upload & transcription
│   │   ├── generate_handler.py    # Artifact generation
│   │   └── base.py                # Handler base class
│   ├── services/
│   │   ├── generators.py          # LLM-powered artifact generators
│   │   ├── db_interface.py        # Supabase operations
│   │   ├── binary_renderer.py     # PDF/PPTX generation
│   │   └── core_merger.py         # Multi-source knowledge merging
│   ├── models/
│   │   ├── artifacts.py           # Pydantic artifact models
│   │   ├── jobs.py                # Job tracking models
│   │   └── protocol.py            # API contracts
│   ├── core/
│   │   ├── knowledge_core.py      # Knowledge graph model
│   │   └── llm_interface.py       # LLM abstraction
│   ├── schema.sql                 # Supabase database schema
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Landing page
│   │   ├── dashboard/
│   │   │   ├── page.tsx           # Project library
│   │   │   ├── canvas/page.tsx    # Main canvas interface
│   │   │   └── settings/page.tsx  # User settings
│   │   └── auth/                  # Authentication pages
│   ├── components/
│   │   ├── canvas/
│   │   │   ├── BeeCanvas.tsx      # Main canvas component
│   │   │   ├── nodes/             # Node types (Asset, Generator, etc.)
│   │   │   └── modals/            # Preview modals
│   │   └── ui/                    # Shadcn/ui components
│   ├── hooks/
│   │   └── useArtifactGenerator.ts # Generation polling hook
│   ├── store/
│   │   └── useCanvasStore.ts      # Zustand canvas state
│   ├── lib/
│   │   ├── api.ts                 # Backend API client
│   │   ├── supabase.ts            # Auth client
│   │   └── auth.ts                # Token management
│   └── public/
│       ├── logo.png               # Brand logo
│       └── sounds/                # UI sound effects
│
└── README.md
```

---

## 🗄️ Database Schema

### Core Tables

| Table | Purpose |
|-------|---------|
| `projects` | User projects (canvas state, name, description) |
| `artifacts` | Generated content (notes, quizzes, flashcards, etc.) |
| `artifact_edges` | DAG relationships between artifacts |
| `jobs` | Background job tracking (ingest, generate) |
| `users` | User accounts and profiles |

### Key Relationships

```
projects ─┬── artifacts ─── artifact_edges
          └── jobs
```

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + Z` | Undo |
| `Ctrl/Cmd + Shift + Z` | Redo |
| `Delete` | Delete selected node |
| `Escape` | Close modals |

---

## 📊 Performance

| Metric | Value |
|--------|-------|
| 60-min video transcription | ~90 seconds |
| Knowledge extraction | ~30 seconds |
| Single artifact generation | ~20 seconds |
| **Complete pipeline** | **< 3 minutes** |
| React Flow rendering | 60 FPS @ 50+ nodes |

---

## 🐛 Known Issues

- Voice isolation requires clips to be uploaded to cloud storage first
- Large video files (>500MB) may experience slower processing
- Some LaTeX math may not render in all artifact types

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Code Style

- **Frontend**: ESLint with Next.js configuration
- **Backend**: Black formatter (100 char line length)
- **Commits**: Conventional commit messages

---

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Google** - Gemini 2.5 Pro for intelligent extraction
- **Azure** - Speech Services for transcription
- **Supabase** - Backend infrastructure
- **Cloudflare** - R2 object storage

---

## 📧 Contact

**Project Links:**
- **GitHub**: [github.com/SquaredPiano/beeprepared](https://github.com/SquaredPiano/beeprepared)
- **Devpost**: [devpost.com/software/beeprepared](https://devpost.com/software/beeprepared)
- **Demo Video**: [youtube.com/watch?v=S2ZwaheHSiY](https://www.youtube.com/watch?v=S2ZwaheHSiY)

---

<div align="center">
  <sub>Built with 🍯 for students who want to study smarter, not harder</sub>
</div>
