# BeePrepared

## The Intentional Knowledge Architecture Platform

---

# Table of Contents

1. [Executive Summary](#executive-summary)
2. [Philosophy & Vision](#philosophy--vision)
3. [Core Concepts](#core-concepts)
4. [Design System](#design-system)
5. [Technical Architecture](#technical-architecture)
6. [Feature Specification](#feature-specification)
7. [User Experience Flows](#user-experience-flows)
8. [Graphic Design Directions](#graphic-design-directions)
9. [Glossary](#glossary)

---

# Executive Summary

**BeePrepared** is an intentional knowledge architecture platform designed to transform raw educational artifacts—PDFs, lecture recordings, video content, and presentation slides—into high-fidelity, structured study materials through a multi-layer cognitive processing pipeline.

The platform operates on the principle that learning materials should be **synthesized, not summarized**. Rather than producing generic flashcards or bullet points, BeePrepared constructs interconnected knowledge artifacts that preserve the pedagogical intent and hierarchical relationships of source material.

The name "BeePrepared" derives from two sources:
1. The industrious, systematic nature of bees—workers who transform raw material (pollen) into refined product (honey)
2. A play on "Be Prepared"—the platform's promise to its users

**Target Users:**
- University students preparing for examinations
- Professionals undertaking certification programs
- Lifelong learners processing dense technical content
- Educators seeking to transform their materials into interactive formats

**Core Value Proposition:**
Transform any educational artifact into flashcards, quizzes, mock examinations, and presentation decks through an intelligent, visual, node-based processing pipeline.

---

# Philosophy & Vision

## Design Philosophy

BeePrepared adheres to a strict design philosophy we call **Architectural Minimalism**—the belief that educational technology should feel like precision instrumentation, not consumer software.

### The Anti-Slop Manifesto

Modern educational technology suffers from what we term "AI slop"—generic gradients, overused components, clichéd layouts, and visual noise that prioritizes novelty over function. BeePrepared rejects this paradigm entirely.

Our design principles:

1. **Intentional Typography**: Every letterform serves a purpose. We use Instrument Sans for mechanical precision and Instrument Serif for warmth and humanity. No decorative fonts, no playful scripts.

2. **Functional Motion**: Animation exists to communicate state, guide attention, or confirm action. We never animate for delight alone. GSAP powers complex timelines; Framer Motion handles transitions.

3. **High-Fidelity Minimalism**: Minimal does not mean empty. Our interfaces are dense with information but never cluttered. White space is architectural, not decorative.

4. **Senior Frontend Principles**: Every component is built as if it were the centerpiece of a design portfolio. No shortcuts, no "good enough."

5. **No Emojis in Production**: The UI speaks through typography, iconography, and structured layout—never through emoji or casual visual language.

### The Hive Metaphor

The bee/hive metaphor is not mere branding—it informs our entire conceptual framework:

| Bee Concept | BeePrepared Equivalent |
|-------------|------------------------|
| Pollen | Raw educational artifacts (PDFs, videos, audio) |
| Worker Bees | Processing agents (extraction, cleaning, synthesis) |
| Honeycomb | The node-based canvas architecture |
| Honey | Refined knowledge artifacts (flashcards, quizzes, exams) |
| The Hive | User's project workspace |
| Nectar Drops | Gamification currency (Honey Points) |

This metaphor extends to our language: users don't "upload files"—they "ingest source material into the Hive." They don't "create projects"—they "initialize a new Hive cell."

### Cognitive Architecture Philosophy

We believe that effective study materials must preserve **cognitive hierarchy**:

```
Source Material
    └── Extracted Concepts (atomic units of knowledge)
            └── Categorized Topics (semantic grouping)
                    └── Synthesized Knowledge Core (relational graph)
                            └── Generated Artifacts (flashcards, quizzes, exams)
```

Each layer builds upon the previous, ensuring that a flashcard isn't just a fact—it's a node in an interconnected knowledge graph.

---

# Core Concepts

## The Ingestion Pipeline

BeePrepared's core innovation is the **Hexagonal Processing Pipeline**—a visual, node-based workflow that transforms source material through distinct processing stages.

### Stage 1: Ingestion
Raw files enter the system. Supported formats:
- **PDF**: Academic papers, textbooks, lecture notes
- **Video (MP4, MOV, AVI)**: Lecture recordings, tutorial content
- **Audio (MP3, WAV)**: Podcast episodes, recorded lectures
- **Presentation (PPTX)**: Slide decks, visual materials

### Stage 2: Extraction
Content is extracted into machine-readable format:
- PDF: OCR and text extraction preserving structure
- Video/Audio: Transcription via speech-to-text
- PPTX: Slide content and speaker notes extraction

### Stage 3: Cleaning
Raw extraction undergoes normalization:
- Removing transcription artifacts
- Correcting OCR errors
- Standardizing formatting
- Removing filler words and verbal hesitations

### Stage 4: Categorization
Cleaned content is semantically analyzed:
- Topic detection and clustering
- Concept extraction
- Relationship mapping
- Importance weighting

### Stage 5: Synthesis
The Knowledge Core is generated:
- Hierarchical concept graph
- Question-answer pair generation
- Difficulty assessment
- Cross-reference linking

### Stage 6: Artifact Generation
Final study materials are produced:
- **Flashcards**: Spaced-repetition optimized Q&A pairs
- **Quizzes**: Multiple-choice assessments with rationales
- **Mock Exams**: Full-length PDF examinations with answer keys
- **Presentation Decks**: Synthesized PPTX summaries

## The Canvas

The Canvas is BeePrepared's visual workflow editor—a node-based interface where users construct their processing pipelines.

### Node Types

**Asset Nodes** (Blue accent)
- Represent source material
- Display file type, name, size
- Provide preview on click
- Source handles only (output)

**Process Nodes** (Dark/Black)
- Represent processing stages
- Display status (pending, processing, complete, error)
- Both target and source handles (input/output)
- Types: Extract, Clean, Categorize, Synthesize

**Result Nodes** (Honey accent)
- Represent generated artifacts
- Display artifact type and preview
- Target handles only (input)
- Types: Flashcards, Quiz, Exam, PPTX

### Edge Connections

Edges represent data flow between nodes:
- **Dotted lines**: Idle/ready state
- **Solid lines**: Active/processing state
- **Animated flow**: Data in transit
- **Color-coded**: Source node type determines edge color

### Constraints

The canvas enforces logical ordering:
1. Asset nodes must exist before Process nodes can be added
2. Process nodes must exist before Result nodes can be added
3. Incompatible connections are visually rejected

## The Knowledge Core

The Knowledge Core is BeePrepared's internal representation of processed content—a JSON document containing:

```json
{
  "metadata": {
    "source": "filename.pdf",
    "processed_at": "2026-01-24T10:30:00Z",
    "confidence_score": 0.94
  },
  "concepts": [
    {
      "id": "c001",
      "term": "Neural Network",
      "definition": "A computational model inspired by biological neural networks...",
      "category": "Machine Learning",
      "difficulty": 3,
      "related": ["c002", "c005", "c012"]
    }
  ],
  "relationships": [
    {
      "source": "c001",
      "target": "c002",
      "type": "prerequisite"
    }
  ],
  "questions": [
    {
      "id": "q001",
      "type": "multiple_choice",
      "stem": "Which architecture introduced self-attention?",
      "options": ["RNN", "LSTM", "Transformer", "CNN"],
      "correct": 2,
      "rationale": "The Transformer architecture, introduced in 'Attention Is All You Need' (2017)...",
      "concept_refs": ["c001", "c005"]
    }
  ]
}
```

## Honey Points (Gamification)

Honey Points ("Nectar Drops") are BeePrepared's gamification currency:

| Action | Points |
|--------|--------|
| Ingest source material | +10 |
| Complete processing pipeline | +25 |
| Review flashcard deck | +5 |
| Complete quiz with 80%+ | +15 |
| Complete mock exam | +50 |
| Daily login streak (7 days) | +100 |

Points unlock:
- Extended processing quotas
- Premium artifact templates
- Advanced analytics dashboards
- Priority processing queue

---

# Design System

## Color Palette

BeePrepared's palette is derived from the natural colors of bees and honey:

### Primary Colors

| Name | Hex | HSL | Usage |
|------|-----|-----|-------|
| **Honey** | `#FCD34F` | 45°, 97%, 65% | Primary accent, CTAs, highlights |
| **Bee Black** | `#0F172A` | 222°, 47%, 11% | Text, dark surfaces, contrast |
| **Cream** | `#FFFBEB` | 48°, 100%, 96% | Backgrounds, canvas |
| **Wax** | `#FDE68A` | 48°, 96%, 77% | Borders, dividers, subtle accents |

### Secondary Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Honey 50** | `#FFFEF5` | Lightest honey tint |
| **Honey 100** | `#FEF3C7` | Hover states |
| **Honey 200** | `#FDE68A` | Active states |
| **Honey 500** | `#F59E0B` | Strong accent |
| **Honey 600** | `#D97706` | Pressed states |
| **Honey 700** | `#B45309` | Dark accent |

### Semantic Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Success** | `#22C55E` | Completed states, positive feedback |
| **Warning** | `#F59E0B` | Caution, pending states |
| **Error** | `#EF4444` | Errors, destructive actions |
| **Info** | `#3B82F6` | Informational, asset nodes |

### Gradients

We use gradients sparingly and only for depth, never decoration:

```css
/* Glass effect */
background: rgba(255, 255, 255, 0.8);
backdrop-filter: blur(24px);
border: 1px solid rgba(253, 230, 138, 0.3);

/* Honey glow */
box-shadow: 0 25px 50px -12px rgba(252, 211, 79, 0.25);

/* Depth overlay */
background: linear-gradient(to top right, transparent, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.1));
```

## Typography

### Font Stack

**Primary (Sans)**: Instrument Sans
- Weights: 400 (Regular), 500 (Medium), 600 (SemiBold), 700 (Bold)
- Usage: Body text, labels, buttons, navigation

**Secondary (Serif)**: Instrument Serif
- Weights: 400 (Regular), 400 Italic
- Usage: Headlines, display text, decorative titles

**Monospace**: JetBrains Mono
- Usage: Code, technical content, data display

### Type Scale

| Name | Size | Weight | Tracking | Usage |
|------|------|--------|----------|-------|
| **Display** | 72px | Bold | -0.02em | Hero headlines |
| **H1** | 48px | Bold | -0.015em | Page titles |
| **H2** | 36px | Bold | -0.01em | Section headers |
| **H3** | 24px | SemiBold | 0 | Subsections |
| **H4** | 20px | SemiBold | 0 | Card titles |
| **Body** | 16px | Regular | 0 | Paragraph text |
| **Body Small** | 14px | Regular | 0 | Secondary text |
| **Caption** | 12px | Medium | 0.05em | Labels, hints |
| **Micro** | 10px | Bold | 0.2em | Uppercase labels |

### Typography Patterns

**Uppercase Micro Labels**:
```css
font-size: 10px;
font-weight: 700;
letter-spacing: 0.2em;
text-transform: uppercase;
color: rgba(15, 23, 42, 0.4);
```

**Display Italics**:
```css
font-family: 'Instrument Serif', serif;
font-style: italic;
opacity: 0.4;
text-transform: lowercase;
```

**Architectural Headlines**:
```css
font-family: 'Instrument Sans', sans-serif;
font-weight: 700;
text-transform: uppercase;
letter-spacing: -0.02em;
line-height: 0.9;
```

## Spacing System

We use an 8px base grid with purposeful density:

| Token | Value | Usage |
|-------|-------|-------|
| `space-1` | 4px | Micro spacing, icon gaps |
| `space-2` | 8px | Tight spacing, inline elements |
| `space-3` | 12px | Compact spacing |
| `space-4` | 16px | Default component padding |
| `space-6` | 24px | Section spacing |
| `space-8` | 32px | Card padding |
| `space-10` | 40px | Large card padding |
| `space-12` | 48px | Section margins |
| `space-16` | 64px | Page margins |
| `space-20` | 80px | Hero spacing |

## Border Radius

We use generous radii for organic, approachable forms:

| Token | Value | Usage |
|-------|-------|-------|
| `rounded-lg` | 12px | Small buttons, inputs |
| `rounded-xl` | 16px | Cards, panels |
| `rounded-2xl` | 20px | Large cards |
| `rounded-3xl` | 24px | Modal headers |
| `rounded-[2rem]` | 32px | Buttons, CTAs |
| `rounded-[2.5rem]` | 40px | Large modals |
| `rounded-[3rem]` | 48px | Feature cards |
| `rounded-[4rem]` | 64px | Hero elements |

## Shadows

We use layered shadows for depth hierarchy:

```css
/* Subtle */
box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);

/* Card */
box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -2px rgba(0, 0, 0, 0.1);

/* Elevated */
box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);

/* Modal */
box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25);

/* Honey Glow */
box-shadow: 0 25px 50px -12px rgba(252, 211, 79, 0.4);

/* Dark Glow */
box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.3);
```

## Glass Morphism

Our signature glass effect:

```css
.glass {
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid rgba(253, 230, 138, 0.3);
}

.glass-dark {
  background: rgba(15, 23, 42, 0.8);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
```

## Iconography

We use Lucide React for consistent, minimal iconography:

**Icon Sizes**:
- 12px: Inline, micro labels
- 14px: Buttons, compact UI
- 16px: Default
- 18px: Emphasis
- 20px: Headers
- 24px: Large buttons
- 32px: Feature icons
- 48px: Hero icons

**Icon Treatment**:
- Stroke width: 1.5px (default)
- Never filled unless indicating state
- Color inherits from text or explicit semantic color
- Hover states: scale(1.1) with transition

---

# Technical Architecture

## Stack Overview

### Frontend

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Framework | Next.js | 16.1.4 | React framework with App Router |
| Runtime | React | 19.2.3 | UI library |
| Language | TypeScript | 5.7+ | Type safety |
| Styling | Tailwind CSS | 4.0 | Utility-first CSS |
| Animation | GSAP | 3.14 | Complex timelines |
| Animation | Framer Motion | 11.15 | Transitions, gestures |
| State | Zustand | 5.0 | Global client state |
| Server State | TanStack Query | 5.62 | Async state, polling |
| Canvas | React Flow | @xyflow/react | Node-based editor |
| Forms | React Hook Form | 7.x | Form management |
| Validation | Zod | 3.x | Schema validation |
| Audio | use-sound | 4.x | Interaction sounds |
| Infrastructure | Vercel | Edge | Deployment, CDN |

### Backend

| Layer | Technology | Purpose |
|-------|------------|---------|
| API | FastAPI | Python REST API |
| Database | Supabase (PostgreSQL) | Relational data, auth |
| Storage | Supabase Storage | File storage (assets) |
| Auth | Supabase Auth | Authentication, OAuth |
| AI/ML | OpenAI API | GPT-4 for synthesis |
| AI/ML | Whisper | Audio transcription |
| Processing | PyMuPDF | PDF extraction |
| Processing | python-pptx | PPTX generation |

### Infrastructure

| Service | Purpose |
|---------|---------|
| Vercel | Frontend hosting, edge functions |
| Supabase | Database, auth, storage, realtime |
| OpenAI | LLM inference |
| GitHub Actions | CI/CD pipelines |

## Directory Structure

```
beeprepared/
├── frontend/                    # Next.js application
│   ├── app/                     # App Router pages
│   │   ├── auth/               # Authentication flows
│   │   │   ├── login/
│   │   │   ├── signup/
│   │   │   └── callback/
│   │   ├── dashboard/          # Protected routes
│   │   │   ├── library/        # Project library
│   │   │   ├── canvas/         # Node editor
│   │   │   ├── flashcards/     # Flashcard viewer
│   │   │   ├── quizzes/        # Quiz interface
│   │   │   ├── mock-exams/     # Exam list
│   │   │   ├── pptx/           # Presentation viewer
│   │   │   └── settings/       # User settings
│   │   ├── artifacts/          # Public artifact view
│   │   ├── share/              # Shared canvas view
│   │   └── processing/         # Processing status
│   ├── components/              # React components
│   │   ├── canvas/             # Canvas-specific
│   │   │   ├── BeeCanvas.tsx
│   │   │   ├── nodes/
│   │   │   └── modals/
│   │   ├── ui/                 # Primitives (shadcn)
│   │   └── [Feature].tsx       # Feature components
│   ├── hooks/                   # Custom hooks
│   ├── lib/                     # Utilities
│   │   ├── supabase/           # Supabase clients
│   │   └── utils/              # Helper functions
│   ├── store/                   # Zustand stores
│   └── public/                  # Static assets
│       └── sounds/             # Interaction audio
├── backend/                     # FastAPI application
│   ├── main.py                 # Entry point
│   ├── models/                 # Pydantic models
│   ├── services/               # Business logic
│   │   ├── extraction.py
│   │   ├── text_cleaning.py
│   │   ├── knowledge_core.py
│   │   └── generators.py
│   ├── scripts/                # Utility scripts
│   └── db/                     # Database schemas
├── docs/                        # Documentation
└── output/                      # Generated artifacts
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│  │  Upload │───▶│ Canvas  │───▶│ Polling │───▶│ Artifact│      │
│  │  Modal  │    │ Editor  │    │ Status  │    │ Viewer  │      │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘      │
│       │              │              ▲              │            │
└───────│──────────────│──────────────│──────────────│────────────┘
        │              │              │              │
        ▼              ▼              │              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        SUPABASE                                 │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│  │ Storage │    │Projects │    │  Tasks  │    │Artifacts│      │
│  │ (Files) │    │ (Meta)  │    │(Status) │    │ (JSON)  │      │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘      │
│       │              │              ▲              ▲            │
└───────│──────────────│──────────────│──────────────│────────────┘
        │              │              │              │
        ▼              ▼              │              │
┌─────────────────────────────────────────────────────────────────┐
│                         BACKEND                                 │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│  │ Ingest  │───▶│ Extract │───▶│Synthesize───▶│Generate │      │
│  │ Worker  │    │ Worker  │    │ Worker  │    │ Worker  │      │
│  └─────────┘    └─────────┘    └─────────┘    └─────────┘      │
│                                      │                          │
│                              ┌───────▼───────┐                  │
│                              │   OpenAI API  │                  │
│                              └───────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
```

## Database Schema

### Core Tables

```sql
-- Users (managed by Supabase Auth)
-- Extended with profile data

CREATE TABLE profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id),
  full_name TEXT,
  avatar_url TEXT,
  honey_points INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Projects (Hive cells)
CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  nodes JSONB DEFAULT '[]',
  edges JSONB DEFAULT '[]',
  viewport JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Assets (Source materials)
CREATE TABLE assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  filename TEXT NOT NULL,
  file_type TEXT NOT NULL,
  file_size BIGINT NOT NULL,
  storage_url TEXT NOT NULL,
  status TEXT DEFAULT 'staged',
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Processing tasks
CREATE TABLE tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  asset_id UUID REFERENCES assets(id) ON DELETE CASCADE,
  type TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  progress INTEGER DEFAULT 0,
  result JSONB,
  error TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Generated artifacts
CREATE TABLE artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  asset_id UUID REFERENCES assets(id),
  type TEXT NOT NULL,
  content JSONB NOT NULL,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Honey points ledger
CREATE TABLE honey_points (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  amount INTEGER NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Shared canvas links
CREATE TABLE shares (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
  canvas_state JSONB NOT NULL,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## State Management

### Zustand Stores

**useFlowStore** - Canvas state
```typescript
interface FlowState {
  nodes: Node[];
  edges: Edge[];
  history: { nodes: Node[]; edges: Edge[] }[];
  historyIndex: number;
  currentProjectId: string | null;
  
  // Actions
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  takeSnapshot: () => void;
  undo: () => void;
  redo: () => void;
  save: () => Promise<void>;
  loadProject: (id: string) => Promise<void>;
}
```

**useIngestionStore** - File upload state
```typescript
interface IngestionState {
  files: File[];
  uploadProgress: Record<string, number>;
  processingStatus: Record<string, TaskStatus>;
  
  // Actions
  addFile: (file: File) => void;
  removeFile: (id: string) => void;
  setProgress: (id: string, progress: number) => void;
  setStatus: (id: string, status: TaskStatus) => void;
}
```

---

# Feature Specification

## Authentication

### Login Flow
1. User navigates to `/auth/login`
2. Enters email/password OR clicks "Continue with Google"
3. On success, redirected to `/dashboard/library`
4. Session persisted via Supabase Auth cookies
5. Middleware protects `/dashboard/*` routes

### Registration Flow
1. User navigates to `/auth/signup`
2. Enters name, email, password
3. Verification email sent
4. User confirms email via link
5. Redirected to onboarding or library

### OAuth Flow
1. User clicks OAuth provider button
2. Redirected to provider consent screen
3. Returns to `/auth/callback` with code
4. Callback exchanges code for session
5. User record created/updated in profiles

## Dashboard

### Library View (`/dashboard/library`)

The Library is the user's project hub:

**Features:**
- Grid/list view of all projects
- Project cards showing name, date, node count
- Search and filter functionality
- Create new project button
- Delete project with confirmation
- Duplicate project
- Quick-access to recent projects

**Project Card Information:**
- Project name (editable inline)
- Created/updated timestamp
- Source material count
- Generated artifact count
- Thumbnail preview (first asset or generic)

### Canvas Editor (`/dashboard/canvas`)

The Canvas is the core workflow editor:

**Toolbar (Top)**
- Ingest: Open asset upload modal
- Process: Add process node
- Result: Add result node
- Run Flow: Execute pipeline

**Sidebar (Left) - Agent Palette**
- Collapsible with localStorage persistence
- Draggable agent cards
- Disabled state when prerequisites missing
- Categories: Source, Processing, Output

**Controls (Bottom Left)**
- Undo/Redo buttons
- Reset View button
- Zoom controls

**Controls (Bottom Right)**
- MiniMap (toggleable)
- Save button

**Context Menu (Right-click)**
- Add nodes by type
- Clear pipeline (with confirmation)
- Node-specific actions

### Flashcards (`/dashboard/flashcards`)

Interactive flashcard study interface:

**Features:**
- Card flip animation (3D CSS transform)
- Navigation: Previous, Next, Restart
- Progress indicator
- Mastery buttons: "Needs Review", "Mastered"
- Deck sidebar with card list
- Session statistics
- Export to Anki format

### Quizzes (`/dashboard/quizzes`)

Multiple-choice quiz interface:

**Features:**
- Question display with options
- Selection state tracking
- Submit and verify answer
- Correct/incorrect feedback
- Rationale display
- Progress bar
- Final score screen
- Restart option

### Mock Exams (`/dashboard/mock-exams`)

Generated examination papers:

**Features:**
- List of generated exams
- Difficulty rating display
- Question count
- PDF download
- Launch exam simulation
- Share exam link

### Presentations (`/dashboard/pptx`)

Generated slide decks:

**Features:**
- Deck grid view
- Slide count and theme
- Preview thumbnails
- Download PPTX
- Launch presentation mode
- Create new from artifact

## Processing Pipeline

### Task Status Flow

```
STAGED → QUEUED → PROCESSING → COMPLETED
                           ↘
                            FAILED
```

**Status Polling:**
- TanStack Query polls `/api/tasks/{id}` every 2 seconds
- Exponential backoff on consecutive failures
- Optimistic UI updates for immediate feedback

### Error Handling

**Recoverable Errors:**
- Network timeout: Auto-retry with backoff
- Rate limit: Queue and retry after cooldown
- Partial failure: Continue with available data

**Non-Recoverable Errors:**
- Invalid file format: User notification
- Corrupt file: User notification
- API key exhausted: Admin notification

---

# User Experience Flows

## First-Time User Journey

```
Landing Page
    │
    ├── "Get Started" CTA
    │         │
    │         ▼
    │    Sign Up Page
    │         │
    │         ├── Email + Password
    │         │         │
    │         │         ▼
    │         │    Email Verification
    │         │         │
    │         │         ▼
    │         │    Onboarding Tour
    │         │
    │         └── OAuth (Google)
    │                   │
    │                   ▼
    │              Dashboard
    │
    ▼
Dashboard (Empty State)
    │
    ├── "Create Your First Hive" CTA
    │         │
    │         ▼
    │    New Project Created
    │         │
    │         ▼
    │    Canvas (Empty State)
    │         │
    │         ├── "Ingest Your First Source" prompt
    │         │         │
    │         │         ▼
    │         │    Asset Upload Modal
    │         │         │
    │         │         ▼
    │         │    File Dropped/Selected
    │         │         │
    │         │         ▼
    │         │    Asset Node Added to Canvas
    │         │
    │         ▼
    │    Process Nodes Available
    │         │
    │         ▼
    │    Result Nodes Available
    │         │
    │         ▼
    │    "Run Flow" Clicked
    │         │
    │         ▼
    │    Processing Status View
    │         │
    │         ▼
    │    Artifacts Generated
    │         │
    │         ▼
    │    Artifact Viewers (Flashcards, Quiz, etc.)
    │
    ▼
Returning User: Library → Existing Project → Canvas
```

## Core Task: Transform PDF to Flashcards

1. **User opens project** or creates new
2. **Clicks "Ingest"** in toolbar
3. **Drops PDF** into upload modal
4. **Asset Node** appears on canvas
5. **Drags "Extract"** agent from sidebar
6. **Auto-connection** links Asset to Extract
7. **Drags "Synthesize"** agent
8. **Auto-connection** links Extract to Synthesize
9. **Drags "Flashcards"** result node
10. **Auto-connection** links Synthesize to Flashcards
11. **Clicks "Run Flow"**
12. **Nodes animate** through processing states
13. **Result node glows** when complete
14. **Clicks Result node** to open Flashcard viewer
15. **Studies flashcards** with flip interaction
16. **Earns Honey Points** for completion

---

# Graphic Design Directions

This section proposes visual directions for marketing materials, social assets, and brand collateral.

## Direction 1: Architectural Blueprint

**Concept:** Position BeePrepared as precision engineering for knowledge.

**Visual Language:**
- Blueprint grid paper textures
- Technical drawing aesthetics
- Isometric illustrations of the processing pipeline
- Cross-section diagrams of "The Hive"
- Engineering notation and measurement marks

**Color Treatment:**
- Primary: Deep navy blue (#0F172A)
- Accent: Blueprint cyan (#00D4FF)
- Honey gold for highlights only
- White linework on dark backgrounds

**Typography:**
- JetBrains Mono for all text
- All-caps with wide letter-spacing
- Technical labels and annotations

**Applications:**
- Hero illustrations showing pipeline as technical schematic
- Social cards with "blueprint" reveals
- Infographics as architectural drawings
- Business cards as mini-blueprints

**Tagline Direction:**
- "Engineered Learning"
- "Architecture for Understanding"
- "Precision Knowledge Synthesis"

---

## Direction 2: Organic Honey Flow

**Concept:** Emphasize the transformation of raw material into refined knowledge through organic, flowing visuals.

**Visual Language:**
- Liquid honey effects (viscous, flowing, dripping)
- Organic blob shapes
- Soft gradients from amber to gold
- Microscopic honeycomb patterns
- Light refracting through honey

**Color Treatment:**
- Warm amber gradient backgrounds
- Rich honey golds with depth
- Cream and ivory for contrast
- Soft shadows for dimensionality

**Typography:**
- Instrument Serif for headlines (italic for emphasis)
- Soft, generous letter-spacing
- Mixed case for approachability

**Applications:**
- Hero illustrations with honey flow animations
- Loading states with honey drip effects
- Icons as honey droplets
- Social cards with liquid gold pours

**Tagline Direction:**
- "Distilled Knowledge"
- "Refined Understanding"
- "From Source to Synthesis"

---

## Direction 3: Modernist Grid

**Concept:** Ultra-minimal Swiss design influence, emphasizing structure and hierarchy.

**Visual Language:**
- Strict grid systems
- Bold geometric shapes
- High contrast black and white with honey accent
- Negative space as design element
- Systematic iconography

**Color Treatment:**
- 90% monochrome (black, white, grays)
- Honey gold as singular accent
- No gradients, flat color only
- Maximum contrast

**Typography:**
- Instrument Sans exclusively
- Bold weights only
- Extreme size contrasts (72px headlines, 10px labels)
- Right-aligned or centered, never justified

**Applications:**
- Poster-style hero sections
- Asymmetric layouts
- Bold typographic statements
- Minimal iconography

**Tagline Direction:**
- "Knowledge. Structured."
- "Study. Refined."
- "Learn. Precisely."

---

## Direction 4: Scientific Journal

**Concept:** Position BeePrepared as academic-grade tooling, borrowing from scientific publication aesthetics.

**Visual Language:**
- Journal article layouts
- Charts, graphs, and data visualizations
- Citation and reference styling
- Margin notes and annotations
- Figure numbers and captions

**Color Treatment:**
- Paper white backgrounds (#FFFEF7)
- Black text with blue hyperlinks
- Muted accent palette
- Subtle cream tints

**Typography:**
- Serif for body text (Instrument Serif)
- Sans for headings and labels
- Traditional academic hierarchy
- Footnotes and superscripts

**Applications:**
- Marketing site as "research paper"
- Case studies as journal articles
- Infographics as scientific figures
- Email templates as abstracts

**Tagline Direction:**
- "Evidence-Based Learning"
- "Peer-Reviewed Preparation"
- "The Science of Study"

---

## Direction 5: Bee Worker Illustrations

**Concept:** Anthropomorphized bee characters representing different processing agents.

**Character Designs:**

**Forager Bee (Extraction)**
- Explorer aesthetic: goggles, satchel, magnifying glass
- Curious expression, forward-leaning posture
- Blue accent color

**Architect Bee (Categorization)**
- Builder aesthetic: hard hat, blueprints, ruler
- Thoughtful expression, measuring gesture
- Green accent color

**Alchemist Bee (Synthesis)**
- Scientist aesthetic: lab coat, beakers, glasses
- Focused expression, mixing gesture
- Purple accent color

**Scribe Bee (Generation)**
- Scholar aesthetic: quill, scroll, ink pot
- Satisfied expression, writing gesture
- Honey accent color

**Visual Language:**
- Flat illustration style with subtle gradients
- Consistent proportions and line weights
- Expressions convey processing states
- Can be animated for status indicators

**Applications:**
- Onboarding illustrations
- Loading states and progress indicators
- Error states with apologetic expressions
- Achievement celebrations

**Tagline Direction:**
- "Your Hive, At Work"
- "Busy Learning, Happy Earning"
- "The Colony Prepares"

---

## Direction 6: Data Visualization Forward

**Concept:** Showcase the knowledge graph and relational data as the hero visual.

**Visual Language:**
- Node-link diagrams
- Force-directed graphs
- Radial hierarchies
- Connection lines with data flow animation
- Clusters and constellations

**Color Treatment:**
- Dark mode primary (#0F172A background)
- Glowing honey nodes
- Connection lines with opacity gradients
- Subtle grid overlay

**Typography:**
- Monospace for data labels
- Sans for UI elements
- Minimal text, data-forward

**Applications:**
- Hero sections with interactive graph
- Knowledge map visualizations
- Processing flow animations
- Relationship explorers

**Tagline Direction:**
- "See the Connections"
- "Knowledge, Mapped"
- "Understanding in Context"

---

## Logo Variations

### Primary Mark

The BeePrepared logo consists of:
1. **Hexagon**: Representing the honeycomb/hive cell
2. **Abstract Bee**: Simplified to geometric forms within hexagon
3. **Wordmark**: "BeePrepared" in Instrument Sans Bold

### Mark Variations

**Icon Only**: Hexagon with bee mark, for favicons, app icons
**Wordmark Only**: Text logotype for horizontal spaces
**Stacked**: Icon above wordmark for square spaces
**Horizontal**: Icon left of wordmark for headers

### Color Variations

**Primary**: Honey on Cream
**Reverse**: Cream on Bee Black
**Monochrome**: Black on White, White on Black
**Accent**: Honey on Bee Black

---

## Illustration Style Guide

### Do's
- Use geometric shapes as building blocks
- Maintain consistent stroke weights (2px at 100%)
- Apply honey gold as primary accent
- Include subtle texture for depth
- Animate purposefully (state changes only)

### Don'ts
- No realistic or photorealistic rendering
- No drop shadows (use layered shapes)
- No more than 4 colors per illustration
- No hand-drawn or sketchy aesthetics
- No decorative elements without function

### Asset Categories

**UI Illustrations**
- Empty states
- Error states
- Loading states
- Success celebrations

**Marketing Illustrations**
- Hero graphics
- Feature explanations
- Process diagrams
- Testimonial decorations

**Social Illustrations**
- Square format cards
- Story format (9:16)
- Cover images
- Profile assets

---

# Glossary

| Term | Definition |
|------|------------|
| **Artifact** | A generated study material (flashcards, quiz, exam, PPTX) |
| **Asset** | A source file uploaded by the user (PDF, video, audio, PPTX) |
| **Canvas** | The visual node-based workflow editor |
| **Edge** | A connection line between nodes on the canvas |
| **Extraction** | The process of converting raw files to text |
| **Hive** | The user's workspace or project |
| **Hive Cell** | A single project within the user's Hive |
| **Honey Points** | Gamification currency earned through platform usage |
| **Ingestion** | The process of uploading and staging source materials |
| **Knowledge Core** | The internal JSON representation of processed content |
| **Nectar Drops** | Colloquial name for Honey Points |
| **Node** | A visual element on the canvas (Asset, Process, or Result) |
| **Pipeline** | The connected flow of nodes representing a processing workflow |
| **Synthesis** | The AI-powered generation of structured knowledge from text |
| **Worker** | A processing agent responsible for a specific transformation |

---

# Appendix: Component Library

## Button Variants

```tsx
// Primary (Honey)
<Button className="bg-honey hover:bg-honey/90 text-bee-black">

// Secondary (Black)
<Button className="bg-bee-black hover:bg-bee-black/90 text-cream">

// Outline
<Button variant="outline" className="border-wax hover:bg-honey/10">

// Ghost
<Button variant="ghost" className="hover:bg-honey/10">

// Destructive
<Button className="bg-red-600 hover:bg-red-700 text-white">
```

## Card Variants

```tsx
// Standard
<Card className="bg-white border-wax rounded-3xl p-8">

// Glass
<Card className="glass rounded-3xl p-8">

// Elevated
<Card className="bg-white border-wax rounded-3xl p-8 shadow-xl">

// Highlighted
<Card className="bg-honey/10 border-honey/30 rounded-3xl p-8">
```

## Input Variants

```tsx
// Default
<Input className="h-12 bg-cream/30 border-wax rounded-xl">

// With Icon
<div className="relative">
  <Icon className="absolute left-3 top-1/2 -translate-y-1/2" />
  <Input className="pl-10 h-12 bg-cream/30 border-wax rounded-xl">
</div>

// Error State
<Input className="h-12 border-red-500 focus:ring-red-500 rounded-xl">
```

---

*Document Version: 1.0.0*
*Last Updated: January 24, 2026*
*Authors: BeePrepared Team*
