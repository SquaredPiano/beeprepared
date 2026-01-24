# BeePrepared

Transform lectures into study materials in under three minutes.

BeePrepared is an AI-powered educational platform that converts lecture recordings, documents, and slides into comprehensive study materials. Upload any lecture format and receive notes, flashcards, practice exams, and audio guides optimized for your learning style.

## Getting Started

### Prerequisites

Before running BeePrepared, ensure you have:

- Python 3.11 or higher
- Node.js 20 or higher
- FFmpeg (for video processing)
- API keys for Azure Speech, Google Gemini, and Supabase

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
cp .env.example .env
```

Edit `.env` with your credentials:
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`
- `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`
- `GEMINI_API_KEY`
- Cloudflare R2 credentials (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`)

5. Initialize the database schema:
```bash
python scripts/apply_supabase_schema.py
```

6. Start the FastAPI server:
```bash
uvicorn main:app --reload
```

The backend will run at `http://localhost:8000`.

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Configure environment variables:
```bash
cp .env.example .env.local
```

Edit `.env.local` with:
- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_API_URL=http://localhost:8000`

4. Start the development server:
```bash
npm run dev
```

The frontend will run at `http://localhost:3000`.

### Testing Your Setup

Verify the extraction pipeline works:
```bash
cd backend
python scripts/test_extraction.py
```

Test database connectivity:
```bash
python scripts/test_supabase_connection.py
```

## Usage

### Uploading Content

1. Navigate to the upload page or click "New Task" in the sidebar
2. Drag and drop your lecture file into the upload zone
3. Select desired artifact types: notes, flashcards, exam, or audio guide
4. Choose difficulty level: beginner, intermediate, or advanced
5. Click upload to begin processing

Supported formats include audio (MP3, WAV, M4A), video (MP4, MOV, AVI), and documents (PDF, PPTX, DOCX, MD, TXT).

### Monitoring Progress

The processing page displays a visual pipeline with four stages:

- **Forager Bee**: Validates and stores your uploaded file
- **Transcriber Bee**: Converts audio to text or extracts document content
- **Extractor Bee**: Identifies key concepts and relationships
- **Builder Bee**: Generates your requested study materials

Real-time progress updates appear every two seconds, showing completion percentage and estimated time remaining.

### Accessing Your Materials

Completed artifacts appear in your library with options to preview PDFs, download files, play audio guides, or regenerate with different settings.

## Technical Architecture

### Frontend Stack

- **Framework**: Next.js 16.1 with App Router and React Server Components
- **UI**: TailwindCSS 4.0 with custom honey-themed design tokens
- **Animation**: GSAP 3.14 for complex motion and Framer Motion 11.15 for transitions
- **Visualization**: React Flow 12.3 for interactive pipeline display
- **State Management**: TanStack Query 5.62 for server state and Zustand 5.0 for client state
- **Components**: Radix UI primitives, React Dropzone 14.3, Lucide React 0.460

### Backend Stack

- **API**: FastAPI with async request handling and Pydantic validation
- **Database**: Supabase PostgreSQL with Row Level Security
- **Storage**: Cloudflare R2 for S3-compatible object storage
- **AI Services**: Azure Speech for transcription, Google Gemini 2.0 for extraction
- **File Processing**: PyMuPDF for PDFs, python-pptx for presentations, FFmpeg for video

### System Design

**HTTP Polling Architecture**

We use HTTP polling instead of WebSockets for real-time updates. The frontend polls the backend every two seconds to fetch task status. This approach provides several advantages for a hackathon project: simpler implementation without connection management, better reliability without firewall issues, easier debugging with standard HTTP requests, and stateless scaling without sticky sessions. For three-minute processing jobs, two-second polling intervals create imperceptible lag while maintaining system simplicity.

**Knowledge Graph Pipeline**

All artifact generators consume a shared knowledge graph rather than working directly from transcripts. The extraction phase runs once, creating a structured representation of lecture concepts with hierarchical relationships, definitions, and examples. This single source of truth prevents divergent outputs and hallucination across different artifact types.

**Parallel Processing**

When users request multiple artifact types, the system processes them concurrently. Four specialized workers handle different artifact types simultaneously, reducing total wait time from sequential processing. Uploading one lecture and generating four artifacts completes in approximately three minutes rather than twelve.

## Project Structure

```
beeprepared/
├── backend/
│   ├── main.py                    # FastAPI application entry
│   ├── routes/
│   │   ├── lectures.py            # File upload endpoints
│   │   ├── tasks.py               # Status polling endpoints
│   │   └── artifacts.py           # Artifact generation
│   ├── services/
│   │   ├── extraction.py          # File format processing
│   │   ├── transcription.py       # Azure Speech integration
│   │   └── text_cleaning.py       # AI-powered cleanup
│   ├── db/
│   │   ├── init.sql               # Database schema
│   │   └── supabase_client.py     # Database operations
│   ├── scripts/
│   │   ├── test_extraction.py
│   │   └── apply_supabase_schema.py
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx               # Landing page
│   │   ├── dashboard/             # User dashboard
│   │   ├── upload/                # File upload interface
│   │   ├── processing/[taskId]/   # Real-time progress
│   │   ├── artifacts/[id]/        # Artifact viewer
│   │   ├── flow/                  # Pipeline canvas
│   │   └── library/               # Artifact library
│   ├── components/
│   │   ├── BeeWorkerPipeline.tsx  # React Flow visualization
│   │   ├── HoneyDropZone.tsx      # Drag and drop upload
│   │   ├── HoneyJar.tsx           # Gamification display
│   │   ├── ProcessingQueue.tsx    # Multi-task tracking
│   │   └── Sidebar.tsx            # Collapsible navigation
│   ├── hooks/
│   │   ├── useTaskPolling.ts      # TanStack Query polling
│   │   └── useTaskQueue.ts        # Multi-task management
│   ├── store/
│   │   └── queueStore.ts          # Zustand state
│   └── lib/
│       ├── supabase.ts            # Auth client
│       └── sounds.ts              # Audio effects
│
└── docs/
    └── architecture.md
```

## Database Schema

### Core Tables

**lectures**: Stores uploaded file metadata including filename, file type, storage URL, file size, duration for audio and video, and processing status.

**transcripts**: Contains extracted text content with word-level timestamps from audio transcription and metadata about language detection and confidence scores.

**knowledge_cores**: Stores structured concept graphs in JSONB format with hierarchical relationships, definitions, examples, and key facts extracted by AI.

**artifacts**: Links generated study materials to source lectures with references to storage URLs, artifact type, difficulty level, and generation parameters.

**processing_tasks**: Tracks real-time status for frontend polling including current stage, progress percentage, active worker type, estimated time remaining, and error messages.

**users**: Records user account information and gamification state including honey points, current streak, longest streak, and achievement level.

**honey_transactions**: Logs all point-earning actions with timestamps and multiplier values for analytics and reward calculations.

### Security

Row Level Security policies ensure users can only access their own data. JWT authentication via Supabase validates all requests. Rate limiting prevents abuse on upload endpoints.

## API Reference

### POST /api/lectures

Upload a new lecture file.

**Request**: Multipart form data with file attachment

**Response**:
```json
{
  "lecture_id": "uuid",
  "task_id": "uuid",
  "filename": "string",
  "status": "queued"
}
```

### GET /api/tasks/{task_id}/status

Poll processing status for real-time updates.

**Response**:
```json
{
  "task_id": "uuid",
  "status": "processing",
  "stage": "extraction",
  "progress": 67,
  "bee_worker": "extractor",
  "eta_seconds": 45
}
```

### POST /api/artifacts/generate

Request artifact generation from an existing lecture.

**Request**:
```json
{
  "lecture_id": "uuid",
  "artifact_type": "notes",
  "difficulty": "intermediate"
}
```

### POST /api/artifacts/generate-batch

Generate multiple artifact types simultaneously.

**Request**:
```json
{
  "lecture_id": "uuid",
  "artifact_types": ["notes", "flashcards", "exam", "audio"],
  "difficulty": "intermediate"
}
```

## Design Philosophy

### Transparency Through Visualization

Students should understand what happens to their uploaded content. The bee worker pipeline visualization shows exactly which processing stage is active, transforming an opaque waiting period into an observable process. This design reduces anxiety and builds trust with users who can see their data moving through each stage.

### Accessibility as Standard

One in five students has a learning disability. Audio outputs serve both accessibility needs and auditory learning preferences. Keyboard navigation supports users with motor impairments and power users who prefer efficient workflows. High contrast mode aids visual disabilities. These features are core to the platform design rather than optional add-ons.

### Gamification with Purpose

Honey points and bee levels create engagement without manipulation. The reward system reinforces positive study habits through streak tracking and level progression. Progress bars provide concrete feedback about advancement while celebration animations feel earned rather than artificial.

### Architectural Simplicity

We chose HTTP polling over WebSockets and avoided microservices complexity despite their technical appeal. These decisions prioritize reliability and maintainability over architectural sophistication. Simple systems ship faster and break less often during critical demonstrations.

## Performance Metrics

### Processing Speed
- 60-minute audio transcription: 90 seconds
- Concept extraction from transcript: 30 seconds
- Single artifact generation: 20 seconds
- Complete pipeline: under 3 minutes

### Frontend Performance
- Initial page load: under 2 seconds
- Time to interactive: under 3 seconds
- Polling overhead: maximum 30 requests per minute
- React Flow rendering: 60 FPS with 50+ nodes

### Backend Scalability
- Concurrent uploads: 100+
- Parallel artifact generation: 4 per worker instance
- Database query latency: under 50ms (p95)
- R2 storage throughput: 5+ MB/s

## Accessibility Compliance

BeePrepared meets WCAG 2.1 AA standards:

- Semantic HTML5 with proper heading hierarchy
- ARIA labels for interactive elements and dynamic content
- Complete keyboard navigation without mouse dependency
- Color contrast ratios exceeding 4.5:1 for all text
- Visible focus indicators on all focusable elements
- Screen reader compatibility with announcements for status changes
- Alternative text for meaningful images
- Captions and transcripts for audio content
- No content flashing more than three times per second
- Responsive design supporting 200% text zoom

## Contributing

We welcome contributions from the community. Please fork the repository, create a feature branch, implement changes with tests, and submit a pull request with a clear description.

### Code Style

- Frontend: ESLint with standard configuration
- Backend: Black formatter with 100-character line length
- Commits: Conventional commit message format
- Documentation: Update README for user-facing changes

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Acknowledgments

This project draws inspiration from several platforms. Eduflow demonstrated the power of visual learning path builders through drag-and-drop course creation. Architex showed how structured outputs can emerge from unstructured inputs. Duolingo proved gamification can enhance learning without manipulation. We adapted these concepts for AI-powered study material generation.

Built with care by students who understand the challenge of exam preparation. We hope BeePrepared makes studying more effective and less stressful.
