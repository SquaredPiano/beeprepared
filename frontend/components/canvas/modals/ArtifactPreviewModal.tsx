"use client";

import React, { useState, useMemo } from "react";
import { 
  Dialog, 
  DialogContent, 
} from "@/components/ui/dialog";
import { 
  Sparkles, 
  HelpCircle, 
  FileText, 
  Presentation,
  BookOpen,
  Layers,
  ClipboardCheck,
  PlayCircle,
  Download,
  Share2,
  Trash2,
  RefreshCw,
  X,
  ChevronLeft,
  ChevronRight,
  Brain,
  Video,
  Music
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Artifact } from "@/lib/api";
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';

const API_BASE = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

// ============================================================================
// Helpers
// ============================================================================

function stripMarkdown(text: string | null | undefined): string {
  if (!text) return '';
  return text
    .replace(/!\[.*?\]\(.*?\)/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\n+/g, ' ')
    .trim();
}

function MathText({ children }: { children: string | null | undefined }) {
  if (!children) return null;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
    >
      {children}
    </ReactMarkdown>
  );
}

function MathTextInline({ children }: { children: string | null | undefined }) {
  if (!children) return <>{children}</>;
  return (
    <span className="math-inline">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {children}
      </ReactMarkdown>
    </span>
  );
}

function normalizeArtifact(type: string, artifact: Artifact | null): any {
  if (!artifact?.content) return null;
  const content = artifact.content;

  switch (type) {
    case 'quiz':
      return content.data || content.core?.quiz || content.quiz || null;
    case 'notes':
      return content.data || content.core?.notes || content.notes || null;
    case 'slides':
      return content.data || content.core?.slides || content.slides || null;
    case 'flashcards':
      return content.data || content.core?.flashcards || content.flashcards || null;
    case 'exam':
      return content.data || content.core?.exam || content.exam || null;
    case 'knowledge_core':
      return content.core || content;
    default:
      return content.data || content;
  }
}

async function downloadBinary(artifactId: string, fallbackFilename: string): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/api/artifacts/${artifactId}/download`);
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    
    const data = await res.json();
    const a = document.createElement('a');
    a.href = data.download_url;
    a.download = data.filename || fallbackFilename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  } catch (error) {
    console.error('[Download] Failed:', error);
    alert(`Download failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
  }
}

function getBinaryInfo(artifact: Artifact | null): { format: string; available: boolean } | null {
  const binary = artifact?.content?.binary;
  if (!binary) return null;
  return {
    format: binary.format || 'bin',
    available: !!binary.storage_path,
  };
}

// ============================================================================
// Renderers
// ============================================================================

function QuizRenderer({ data }: { data: any }) {
  const [answers, setAnswers] = useState<Record<string, number>>({});

  if (!data?.questions) return <EmptyState message="No quiz data" />;

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-bee-black">{data.title || 'Quiz'}</h2>
      {data.questions.map((q: any, idx: number) => {
        const answered = answers[q.id] !== undefined;
        const selected = answers[q.id];
        const correct = selected === q.correct_answer_index;

        return (
          <div key={q.id || idx} className="p-4 bg-white rounded-2xl border border-wax">
            <div className="font-medium mb-3">
              <span className="text-honey font-bold mr-2">{idx + 1}.</span>
              <MathTextInline>{q.text}</MathTextInline>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {q.options?.map((opt: string, i: number) => (
                <button
                  key={i}
                  className={`p-3 rounded-xl text-left text-sm transition-all ${
                    answered 
                      ? i === q.correct_answer_index 
                        ? 'bg-green-100 border-green-300 border-2' 
                        : i === selected 
                          ? 'bg-red-100 border-red-300 border-2' 
                          : 'bg-gray-50 border-gray-200 border opacity-50'
                      : 'bg-cream hover:bg-honey/10 border border-wax cursor-pointer'
                  }`}
                  onClick={() => !answered && setAnswers(p => ({ ...p, [q.id || idx]: i }))}
                  disabled={answered}
                >
                  <MathTextInline>{opt}</MathTextInline>
                </button>
              ))}
            </div>
            {answered && (
              <div className={`mt-3 p-3 rounded-xl text-sm ${correct ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'}`}>
                {correct ? '✓ Correct!' : '✗ Incorrect.'} <MathTextInline>{q.explanation}</MathTextInline>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function NotesRenderer({ data }: { data: any }) {
  if (data?.format === 'markdown' && data?.body) {
    return (
      <div className="prose prose-sm max-w-none">
        <h1 className="text-2xl font-bold text-bee-black mb-6">{data.title || 'Notes'}</h1>
        <div className="bg-white p-6 rounded-2xl border border-wax">
          <MathText>{data.body}</MathText>
        </div>
      </div>
    );
  }
  
  if (!data?.sections) return <EmptyState message="No notes data" />;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-bee-black">{data.title || 'Notes'}</h1>
      {data.sections.map((sec: any, i: number) => (
        <div key={i} className="bg-white p-6 rounded-2xl border border-wax space-y-4">
          <h2 className="text-lg font-bold text-bee-black">{sec.heading}</h2>
          
          {sec.key_points && sec.key_points.length > 0 && (
            <ul className="list-disc list-inside space-y-1 text-sm">
              {sec.key_points.map((kp: string, k: number) => (
                <li key={k}><MathTextInline>{kp}</MathTextInline></li>
              ))}
            </ul>
          )}
          
          {sec.content_block && (
            <div className="prose prose-sm max-w-none">
              <MathText>{sec.content_block}</MathText>
            </div>
          )}
          
          {sec.key_terms && sec.key_terms.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <span className="text-xs font-bold text-bee-black/40">Key Terms:</span>
              {sec.key_terms.map((term: string, t: number) => (
                <span key={t} className="px-2 py-1 bg-honey/10 text-honey-700 text-xs rounded-full font-medium">{term}</span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function SlidesRenderer({ data, artifact }: { data: any; artifact: Artifact | null }) {
  if (!data?.slides) return <EmptyState message="No slides data" />;

  const binaryInfo = getBinaryInfo(artifact);

  const downloadJSON = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'slides.json';
    a.click();
  };

  const handleDownloadPPTX = () => {
    if (!binaryInfo?.available) {
      alert('PPTX not yet generated. Please wait for processing to complete.');
      return;
    }
    if (artifact?.id) {
      downloadBinary(artifact.id, 'slides.pptx');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-bee-black">{data.title || 'Slides'}</h2>
        <div className="flex gap-2">
          <Button 
            onClick={handleDownloadPPTX} 
            className="bg-bee-black text-white hover:bg-honey hover:text-bee-black"
            disabled={!binaryInfo?.available}
          >
            <Presentation className="w-4 h-4 mr-2" /> Download PPTX
          </Button>
          <Button variant="outline" onClick={downloadJSON}>
            <FileText className="w-4 h-4 mr-2" /> JSON
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {data.slides.map((slide: any, i: number) => (
          <div key={i} className="bg-white p-6 rounded-2xl border border-wax aspect-video flex flex-col">
            <h3 className="font-bold text-bee-black mb-2">{stripMarkdown(slide.heading)}</h3>
            <p className="text-sm text-bee-black/60 mb-3">{stripMarkdown(slide.main_idea)}</p>
            <ul className="text-xs space-y-1 flex-1">
              {slide.bullet_points?.slice(0, 4).map((bp: string, b: number) => (
                <li key={b} className="flex items-start gap-2">
                  <span className="text-honey">•</span>
                  {stripMarkdown(bp)}
                </li>
              ))}
            </ul>
            <div className="text-[10px] text-bee-black/30 mt-2">Slide {i + 1}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FlashcardRenderer({ data }: { data: any }) {
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);

  if (!data?.cards || data.cards.length === 0) {
    return <EmptyState message="No flashcard data" />;
  }

  const card = data.cards[index];
  const next = () => { setFlipped(false); setTimeout(() => setIndex(i => (i + 1) % data.cards.length), 200); };
  const prev = () => { setFlipped(false); setTimeout(() => setIndex(i => (i - 1 + data.cards.length) % data.cards.length), 200); };

  return (
    <div className="flex flex-col items-center">
      <div 
        onClick={() => setFlipped(!flipped)}
        className={`
          w-full max-w-md aspect-[3/2] cursor-pointer perspective-1000
          transition-transform duration-500
          ${flipped ? 'rotate-y-180' : ''}
        `}
      >
        <div className={`
          relative w-full h-full transition-transform duration-500 transform-style-3d
          ${flipped ? '[transform:rotateY(180deg)]' : ''}
        `}>
          {/* Front */}
          <div className="absolute inset-0 backface-hidden bg-white rounded-3xl border-2 border-honey shadow-xl p-8 flex flex-col items-center justify-center text-center">
            <Badge className="bg-honey/10 text-honey mb-4">Question</Badge>
            <div className="text-lg font-medium">
              <MathText>{card.front}</MathText>
            </div>
            <p className="text-xs text-bee-black/30 mt-4">Click to flip</p>
          </div>
          
          {/* Back */}
          <div className="absolute inset-0 backface-hidden [transform:rotateY(180deg)] bg-bee-black text-white rounded-3xl shadow-xl p-8 flex flex-col items-center justify-center text-center">
            <Badge className="bg-honey text-bee-black mb-4">Answer</Badge>
            <div className="text-lg">
              <MathText>{card.back}</MathText>
            </div>
            {card.hint && (
              <p className="text-xs text-white/50 mt-4">💡 {card.hint}</p>
            )}
          </div>
        </div>
      </div>
      
      <div className="flex items-center gap-6 mt-8">
        <Button variant="outline" onClick={prev} className="rounded-full w-12 h-12 p-0">
          <ChevronLeft className="w-5 h-5" />
        </Button>
        <span className="text-sm font-bold text-bee-black/60">
          {index + 1} / {data.cards.length}
        </span>
        <Button variant="outline" onClick={next} className="rounded-full w-12 h-12 p-0">
          <ChevronRight className="w-5 h-5" />
        </Button>
      </div>
    </div>
  );
}

function ExamRenderer({ data, artifact }: { data: any; artifact: Artifact | null }) {
  const [showAnswers, setShowAnswers] = useState(false);
  const binaryInfo = getBinaryInfo(artifact);

  if (!data?.questions || data.questions.length === 0) {
    return <EmptyState message="No exam questions generated" />;
  }

  const handleDownloadPDF = () => {
    if (artifact?.id) {
      downloadBinary(artifact.id, 'final_exam.pdf');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-bee-black">{data.title || 'Final Exam'}</h2>
        <div className="flex gap-2">
          {binaryInfo?.available && (
            <Button onClick={handleDownloadPDF} className="bg-bee-black text-white hover:bg-honey hover:text-bee-black">
              <FileText className="w-4 h-4 mr-2" /> Download PDF
            </Button>
          )}
          <Button variant="outline" onClick={() => setShowAnswers(!showAnswers)}>
            {showAnswers ? 'Hide Answers' : 'Show Answers'}
          </Button>
        </div>
      </div>

      {data.instructions && (
        <div className="p-4 bg-blue-50 rounded-xl text-sm text-blue-800">
          <strong>Instructions:</strong> {data.instructions}
        </div>
      )}

      <div className="space-y-4">
        {data.questions.map((q: any, idx: number) => (
          <div key={q.id || idx} className="bg-white p-6 rounded-2xl border border-wax">
            <div className="flex items-center justify-between mb-3">
              <span className="font-bold text-honey">Q{idx + 1}</span>
              <div className="flex gap-2">
                <Badge variant="outline">{q.type}</Badge>
                <Badge className="bg-honey/10 text-honey">{q.points} pts</Badge>
              </div>
            </div>
            <p className="font-medium mb-3">{stripMarkdown(q.text)}</p>

            {q.options && q.type === 'MCQ' && (
              <div className="space-y-2 mb-3">
                {q.options.map((opt: string, i: number) => (
                  <div key={i} className="p-2 bg-cream rounded-lg text-sm">
                    {String.fromCharCode(65 + i)}. {stripMarkdown(opt)}
                  </div>
                ))}
              </div>
            )}

            {showAnswers && (
              <div className="mt-4 pt-4 border-t border-wax space-y-2">
                <div className="text-sm">
                  <strong className="text-green-600">Model Answer:</strong>{' '}
                  {stripMarkdown(q.model_answer || 'See grading notes')}
                </div>
                {q.grading_notes && (
                  <div className="text-xs text-bee-black/60">
                    <strong>Grading:</strong> {stripMarkdown(q.grading_notes)}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function KnowledgeCoreRenderer({ data }: { data: any }) {
  if (!data) return <EmptyState message="No knowledge core data" />;

  const concepts = data.concepts || [];
  const title = data.title || 'Knowledge Core';

  return (
    <div className="space-y-6">
      <div className="text-center mb-8">
        <div className="w-20 h-20 mx-auto bg-amber-100 rounded-full flex items-center justify-center mb-4">
          <Brain className="w-10 h-10 text-amber-600" />
        </div>
        <h2 className="text-2xl font-bold text-bee-black">{title}</h2>
        <p className="text-sm text-bee-black/40 mt-2">
          {concepts.length} concepts extracted
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {concepts.slice(0, 8).map((concept: any, i: number) => (
          <div key={i} className="bg-white p-4 rounded-2xl border border-wax">
            <h3 className="font-bold text-bee-black mb-2">{concept.name || concept.title || `Concept ${i + 1}`}</h3>
            <p className="text-sm text-bee-black/60 line-clamp-3">
              {concept.description || concept.summary || 'No description available'}
            </p>
          </div>
        ))}
      </div>

      {concepts.length > 8 && (
        <p className="text-center text-sm text-bee-black/40">
          + {concepts.length - 8} more concepts
        </p>
      )}
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-16 h-16 bg-cream rounded-full flex items-center justify-center mb-4">
        <FileText className="w-8 h-8 text-bee-black/20" />
      </div>
      <p className="text-sm text-bee-black/40">{message}</p>
    </div>
  );
}

// ============================================================================
// Icon Mapping
// ============================================================================

const TYPE_ICONS: Record<string, typeof FileText> = {
  video: Video,
  audio: Music,
  text: FileText,
  flat_text: FileText,
  knowledge_core: Brain,
  quiz: HelpCircle,
  flashcards: Layers,
  notes: BookOpen,
  slides: Presentation,
  exam: ClipboardCheck,
};

const TYPE_LABELS: Record<string, string> = {
  video: 'Video',
  audio: 'Audio',
  text: 'Text',
  flat_text: 'Cleaned Text',
  knowledge_core: 'Knowledge Core',
  quiz: 'Quiz',
  flashcards: 'Flashcards',
  notes: 'Notes',
  slides: 'Slides',
  exam: 'Exam',
};

// ============================================================================
// Main Component
// ============================================================================

interface ArtifactPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  artifact: Artifact | null;
  onRegenerate?: () => void;
  isRegenerating?: boolean;
}

export function ArtifactPreviewModal({ 
  isOpen, 
  onClose, 
  artifact,
  onRegenerate,
  isRegenerating = false,
}: ArtifactPreviewModalProps) {
  if (!artifact) return null;

  const artifactType = artifact.type || 'text';
  const Icon = TYPE_ICONS[artifactType] || FileText;
  const label = TYPE_LABELS[artifactType] || artifactType;
  const data = useMemo(() => normalizeArtifact(artifactType, artifact), [artifact, artifactType]);

  const renderContent = () => {
    switch (artifactType) {
      case 'quiz':
        return <QuizRenderer data={data} />;
      case 'notes':
        return <NotesRenderer data={data} />;
      case 'slides':
        return <SlidesRenderer data={data} artifact={artifact} />;
      case 'flashcards':
        return <FlashcardRenderer data={data} />;
      case 'exam':
        return <ExamRenderer data={data} artifact={artifact} />;
      case 'knowledge_core':
        return <KnowledgeCoreRenderer data={data} />;
      default:
        return (
          <div className="bg-white p-6 rounded-2xl border border-wax">
            <pre className="text-xs overflow-auto max-h-96">
              {JSON.stringify(data, null, 2)}
            </pre>
          </div>
        );
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] rounded-[32px] border-wax bg-cream/95 backdrop-blur-xl p-0 overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-cream/95 backdrop-blur-xl border-b border-wax p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-white shadow-lg flex items-center justify-center border border-wax">
              <Icon className="w-6 h-6 text-honey" />
            </div>
            <div>
              <Badge className="bg-honey/10 text-honey border-none text-[10px] uppercase tracking-widest font-bold mb-1">
                {label}
              </Badge>
              <h2 className="text-xl font-bold text-bee-black">
                {artifact.content?.title || artifact.content?.data?.title || label}
              </h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {onRegenerate && (
              <Button 
                variant="outline" 
                onClick={onRegenerate}
                disabled={isRegenerating}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isRegenerating ? 'animate-spin' : ''}`} />
                {isRegenerating ? 'Regenerating...' : 'Regenerate'}
              </Button>
            )}
            <Button variant="ghost" size="icon" onClick={onClose} className="rounded-full">
              <X className="w-5 h-5" />
            </Button>
          </div>
        </div>

        {/* Content */}
        <div className="p-6 overflow-y-auto max-h-[calc(90vh-180px)]">
          {renderContent()}
        </div>

        {/* Footer */}
        <div className="sticky bottom-0 bg-cream/95 backdrop-blur-xl border-t border-wax p-4 flex justify-between items-center">
          <div className="flex gap-4">
            <button className="text-[10px] font-bold uppercase tracking-widest text-bee-black/40 hover:text-bee-black transition-colors flex items-center gap-2">
              <Share2 size={14} /> Share
            </button>
          </div>
          <div className="text-[10px] text-bee-black/30">
            Created {new Date(artifact.created_at).toLocaleDateString()}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
