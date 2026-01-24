# BeePrepared 🐝

**Transform lectures into study materials. Buzzworthy fast.**

BeePrepared is an AI-powered educational platform that converts passive learning content (lecture recordings, slides, documents) into active study materials (notes, flashcards, practice exams, audio guides). Built for students drowning in recorded lectures with no efficient way to extract actionable study materials.

## 🎯 The Problem

Students spend hours re-watching lectures, manually creating notes, and struggling to prepare for exams. Traditional study methods don't scale with the volume of content in modern online education.

## ✨ Our Solution

**Upload any lecture format → AI processes it → Download comprehensive, ready-to-use study materials**

### Key Features

- **🎤 Audio/Video Transcription**: Azure Speech for high-accuracy transcription of lectures
- **📄 Document Extraction**: Full text extraction from PDF, PPTX, DOCX, MD, TXT
- **🐝 Bee-Themed Pipeline**: Real-time visualization of processing stages (Forager → Transcriber → Extractor → Builder)
- **🎨 Beautiful Frontend**: Next.js 16.1 with GSAP animations and React Flow pipeline visualization
- **🍯 Gamification**: Honey points system with streak tracking and levels
- **♿ Accessibility**: WCAG 2.1 AA compliant, keyboard navigation, high contrast mode

## 🏗️ Architecture

### Tech Stack

**Frontend:**
- Next.js 16.1 (React 19.2, App Router)
- TailwindCSS 4.0 with custom bee theme
- GSAP 3.14 + Framer Motion (animations)
- React Flow (pipeline visualization)
- TanStack Query (polling & state)
- Zustand (client state)

**Backend:**
- FastAPI (Python async)
- Supabase (PostgreSQL + Auth)
- Cloudflare R2 (file storage)
- Azure Speech (transcription)
- Google Gemini 2.0 (AI processing)

### File Format Support

| Format | Status | Details |
|--------|--------|---------|
| PDF | ✅ | PyMuPDF extraction |
| PPTX | ✅ | python-pptx (slides + notes) |
| DOCX | ✅ | python-docx |
| MD/TXT | ✅ | Direct read |
| Audio (WAV, MP3, M4A) | ✅ | Azure Speech transcription |
| Video (MP4, MOV, AVI) | ✅ | FFmpeg audio extraction → transcription |

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+** (Backend)
- **Node.js 20+** (Frontend)
- **FFmpeg** (for video processing)

### Backend Setup

1. **Navigate to backend:**
   ```bash
   cd backend
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   ```

3. **Activate environment:**
   - Windows: `.\venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

4. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

5. **Configure environment variables:**
   - Copy `.env.example` to `.env`
   - Fill in your API keys:
     - `SUPABASE_URL` and `SUPABASE_KEY`
     - `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`
     - `GEMINI_API_KEY`
     - `R2_*` credentials (Cloudflare R2)

6. **Apply database schema:**
   ```bash
   python scripts/apply_supabase_schema.py
   ```

7. **Start the server:**
   ```bash
   uvicorn main:app --reload
   ```
   Backend runs on `http://localhost:8000`

### Frontend Setup

1. **Navigate to frontend:**
   ```bash
   cd frontend
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Configure environment:**
   - Copy `.env.example` to `.env.local`
   - Set `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - Set `NEXT_PUBLIC_API_URL=http://localhost:8000`

4. **Start development server:**
   ```bash
   npm run dev
   ```
   Frontend runs on `http://localhost:3000`

## 🧪 Testing

### Test Extraction Pipeline

```bash
cd backend
python scripts/test_extraction.py
```

Tests all supported file formats (PDF, PPTX, audio, video).

### Test Database Connection

```bash
cd backend
python scripts/test_supabase_connection.py
```

Verifies Supabase connection and CRUD operations.

## 📁 Project Structure

```
beeprepared/
├── backend/
│   ├── extraction.py          # File format → text extraction
│   ├── text_cleaning.py       # AI-powered text cleaning
│   ├── ingest.py             # R2 upload service
│   ├── db/
│   │   └── init.sql          # Database schema
│   ├── scripts/
│   │   ├── test_extraction.py
│   │   └── test_supabase_connection.py
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx          # Landing page
│   │   ├── upload/           # File upload interface
│   │   ├── processing/       # Real-time progress
│   │   └── dashboard/        # User dashboard
│   ├── components/
│   │   ├── BeeWorkerPipeline.tsx    # React Flow visualization
│   │   ├── HoneyDropZone.tsx        # Drag & drop upload
│   │   └── HoneyJar.tsx             # Gamification display
│   ├── hooks/
│   │   └── useTaskPolling.ts        # 2s polling hook
│   └── store/
│       └── ingestionStore.ts        # Zustand state
│
└── README.md
```

## 🎨 Design Philosophy

1. **Transparency Over Magic** - Users see exactly what's happening
2. **Delight Through Metaphor** - Bee colony isn't just branding, it's functional
3. **Accessibility First** - WCAG 2.1 AA compliant from day one
4. **Speed as Feature** - 3-minute processing is a competitive advantage

## 🐝 Bee Worker Pipeline

```
Forager 🐝    →    Transcriber 🐝    →    Extractor 🐝    →    Builder 🐝
(Upload)          (Audio → Text)         (AI Analysis)        (Generate Artifacts)
```

## 🍯 Gamification

- **Honey Points**: Earned for each action
- **Streak Bonuses**: Daily use multipliers (up to 2x)
- **Levels**: Larva → Worker → Drone → Queen
- **Progress Tracking**: Visual honey jar fills as you level up

## 📊 Database Schema

- `lectures` - Uploaded file metadata
- `transcripts` - Extracted text content
- `processing_tasks` - Real-time status tracking

## 🔒 Security

- OAuth 2.0 via Supabase
- Row Level Security (RLS) policies
- Rate limiting on all endpoints
- File type validation (magic byte verification)
- Sanitized filenames

## 🤝 Contributing

We welcome contributions! This project was built for the HackHive hackathon.

## 📄 License

MIT License - feel free to use this for your own projects!

## 🙏 Acknowledgments

- Azure AI Speech for transcription
- Google Gemini for AI processing
- Supabase for instant backend
- Cloudflare R2 for zero-egress storage

---

**Built with 💛 by the BeePrepared team**
