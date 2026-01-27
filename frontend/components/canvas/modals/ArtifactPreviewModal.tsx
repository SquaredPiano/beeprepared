"use client";

import React, { useState, useMemo, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  HelpCircle,
  FileText,
  Presentation,
  BookOpen,
  Layers,
  ClipboardCheck,
  Share2,
  RefreshCw,
  X,
  ChevronLeft,
  ChevronRight,
  Brain,
  Video,
  Music,
  Award,
  CheckCircle2,
  XCircle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Artifact, api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import MDEditor from '@uiw/react-md-editor';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import { supabase } from "@/lib/supabase";

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

/**
 * Smart Math Text Renderer
 * Detects LaTeX patterns and wraps in delimiters if missing to ensure proper rendering.
 * Prevents Markdown from swallowing backslashes in math formulas.
 */
const MarkdownRenderers = {
  h1: ({ children }: any) => (
    <h1 className="text-3xl md:text-4xl font-serif font-bold text-bee-black mb-6 mt-8 pb-4 border-b-2 border-honey/20 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }: any) => (
    <h2 className="text-2xl md:text-3xl font-serif font-bold text-bee-black mb-4 mt-8 flex items-center gap-2">
      <span className="w-2 h-8 bg-honey rounded-full block" />
      {children}
    </h2>
  ),
  h3: ({ children }: any) => (
    <h3 className="text-xl md:text-2xl font-serif font-semibold text-bee-black/80 mb-3 mt-6">
      {children}
    </h3>
  ),
  p: ({ children }: any) => (
    <p className="text-bee-black/90 font-sans leading-relaxed text-lg mb-6 max-w-none text-justify">
      {children}
    </p>
  ),
  ul: ({ children }: any) => (
    <ul className="list-disc pl-6 space-y-2 mb-6 text-bee-black/80 marker:text-honey">
      {children}
    </ul>
  ),
  ol: ({ children }: any) => (
    <ol className="list-decimal pl-6 space-y-2 mb-6 text-bee-black/80 marker:text-honey marker:font-bold">
      {children}
    </ol>
  ),
  li: ({ children }: any) => (
    <li className="pl-1 leading-relaxed">
      {children}
    </li>
  ),
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-4 border-honey bg-honey/5 p-6 my-8 rounded-r-2xl italic text-bee-black/70 font-serif text-xl">
      {children}
    </blockquote>
  ),
  code: ({ className, children }: any) => {
    return (
      <code className={cn(
        "font-mono text-sm px-1.5 py-0.5 rounded bg-bee-black/5 text-bee-black/80",
        className?.includes('language-') ? "block w-full overflow-x-auto p-4 bg-bee-black/90 text-cream my-6 rounded-xl" : ""
      )}>
        {children}
      </code>
    );
  },
  hr: () => <hr className="my-8 border-honey/20" />
};

function MathText({ children }: { children: string | null | undefined }) {
  if (!children) return null;

  let content = children;

  // Heuristic: If text contains common LaTeX commands but NO (or distinct) delimiters, wrap it.
  const latexPatterns = [
    /\\frac/, /\\int/, /\\sum/, /\\prod/, /\\partial/, /\\sqrt/, /\\cdot/, /\\infty/,
    /\\alpha/, /\\beta/, /\\theta/, /\\sigma/, /\\omega/, /\\pi/,
    /\\mathbf/, /\\mathrm/, /\\text/, /\\begin\{/, /\\end\{/
  ];

  const hasLatex = latexPatterns.some(p => p.test(content));
  const hasDelimiters = content.includes('$') || content.includes('\\(') || content.includes('\\[');

  if (hasLatex && !hasDelimiters) {
    if (content.length > 50 || content.includes('\\\\')) {
      content = `$$\n${content}\n$$`;
    } else {
      content = `$${content}$`;
    }
  }

  return (
    <div className="prose-honey w-full max-w-none">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={MarkdownRenderers}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function MathTextInline({ children }: { children: string | null | undefined }) {
  if (!children) return null;
  return (
    <span className="math-inline">
      <MathText>{children}</MathText>
    </span>
  );
}

function normalizeArtifact(type: string, artifact: Artifact | null): any {
  if (!artifact?.content) return null;
  const content = artifact.content;

  // Helper to ensure we don't strip the root key if the renderer needs it
  // But also handle cases where content IS the data directly
  const wrap = (key: string, data: any) => {
    if (!data) return null;
    // If data already has the key, return it as is
    if (data[key]) return data;
    // Otherwise wrap it
    return { [key]: data };
  };

  switch (type) {
    case 'quiz':
      // QuizRenderer expects { questions: [...] }
      // Content might be { quiz: { questions: ... } } or { questions: ... } or { data: { questions: ... } }
      const quizData = content.data || content.core?.quiz || content.quiz || content;
      if (quizData?.questions) return quizData;
      return null;

    case 'notes':
      // NotesRenderer expects { markdown: string } or string
      const notesData = content.data || content.core?.notes || content.notes || content;
      // If it's just a string, wrap it? No, renderer handles string.
      // But we prefer consistent object.
      if (typeof notesData === 'string') return { markdown: notesData };
      if (notesData?.markdown || notesData?.content) return notesData;
      // Fallback for legacy
      if (notesData?.sections) return { markdown: "Legacy notes format not supported in editor." };
      return { markdown: "" }; // Default empty

    case 'slides':
      // SlidesRenderer expects { slides: [...] }
      const slidesData = content.data || content.core?.slides || content.slides || content;
      if (slidesData?.slides) return slidesData;
      return null;

    case 'flashcards':
      // FlashcardRenderer expects { flashcards: [...] }
      const fcData = content.data || content.core?.flashcards || content.flashcards || content;
      // Handle "cards" vs "flashcards" key
      if (fcData?.flashcards) return fcData;
      if (fcData?.cards) return { flashcards: fcData.cards };
      return null;

    case 'exam':
      // ExamRenderer expects { questions: [...] }
      const examData = content.data || content.core?.exam || content.exam || content;
      if (examData?.questions) return examData;
      return null;

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
      throw new Error(`HTTP ${res.status}`);
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
    alert('Download failed');
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
  const [currentIndex, setCurrentIndex] = useState(0);
  const [showSummary, setShowSummary] = useState(false);

  if (!data?.questions) return <EmptyState message="No quiz data" />;

  const currentQuestion = data.questions[currentIndex];
  const total = data.questions.length;
  const answeredCount = Object.keys(answers).length;
  const correctCount = data.questions.filter((q: any, i: number) =>
    answers[q.id || i] === q.correct_answer_index
  ).length;

  const handleSelect = (qIdx: number, optionIdx: number) => {
    if (answers[qIdx] !== undefined) return;
    if (navigator.vibrate) navigator.vibrate(50);
    setAnswers(prev => ({ ...prev, [qIdx]: optionIdx }));

    if (currentIndex < total - 1) {
      setTimeout(() => setCurrentIndex(c => c + 1), 1500);
    } else {
      setTimeout(() => setShowSummary(true), 1500);
    }
  };

  if (showSummary) {
    return (
      <div className="bg-bee-black min-h-full flex flex-col items-center justify-center p-12 text-center text-white">
        <div className="w-32 h-32 bg-honey/10 rounded-full flex items-center justify-center mb-8 border border-honey/20 shadow-[0_0_40px_-10px_rgba(251,191,36,0.3)]">
          <Award className="w-16 h-16 text-honey" />
        </div>
        <h2 className="text-4xl font-serif font-bold text-white mb-3">Quiz Complete</h2>
        <p className="text-white/40 font-medium uppercase tracking-widest text-sm mb-12">Performance Report</p>

        <div className="bg-white/5 border border-white/10 rounded-3xl p-8 mb-12 min-w-[300px]">
          <div className="text-6xl font-bold text-honey mb-2 tabular-nums">
            {Math.round((correctCount / total) * 100)}%
          </div>
          <div className="flex items-center justify-center gap-2 text-white/60 text-sm font-medium">
            <CheckCircle2 size={16} className="text-green-500" />
            <span>{correctCount} Correct</span>
            <span className="mx-2 opacity-20">|</span>
            <XCircle size={16} className="text-red-500" />
            <span>{total - correctCount} Incorrect</span>
          </div>
        </div>

        <Button
          onClick={() => { setAnswers({}); setCurrentIndex(0); setShowSummary(false); }}
          className="bg-honey text-bee-black px-10 py-7 rounded-2xl text-sm font-bold uppercase tracking-widest hover:bg-white hover:scale-105 transition-all w-full max-w-sm"
        >
          Retake Quiz
        </Button>
      </div>
    );
  }

  const isAnswered = answers[currentIndex] !== undefined;
  const selectedIdx = answers[currentIndex];
  const correctIdx = currentQuestion.correct_answer_index;

  return (
    <div className="h-full bg-white text-bee-black flex flex-col">
      {/* Progress Header */}
      <div className="p-8 pb-4 shrink-0 border-b border-wax">
        <div className="flex justify-between items-center mb-6">
          <span className="text-[10px] font-bold uppercase tracking-[0.2em] text-bee-black/30">
            Question {currentIndex + 1} / {total}
          </span>
          <div className="flex gap-1">
            {data.questions.map((_: any, idx: number) => (
              <div
                key={idx}
                className={cn(
                  "h-1.5 w-6 rounded-full transition-all duration-300",
                  idx === currentIndex ? "bg-honey w-12 shadow-sm" :
                    idx < currentIndex ? (answers[idx] === data.questions[idx].correct_answer_index ? "bg-green-500/80" : "bg-red-500/80") :
                      "bg-bee-black/5"
                )}
              />
            ))}
          </div>
        </div>
      </div>

      {/* Main Question Area */}
      <div className="flex-1 overflow-y-auto px-8 pb-8 custom-scrollbar bg-cream/30">
        <div className="max-w-3xl mx-auto h-full flex flex-col justify-center min-h-[500px]">
          <h3 className="text-2xl md:text-3xl font-serif font-bold leading-relaxed mb-12 text-bee-black/90 selection:bg-honey/30">
            <MathText>{currentQuestion.text}</MathText>
          </h3>

          <div className="grid gap-4">
            {currentQuestion.options?.map((opt: string, idx: number) => {
              const isSelected = isAnswered && idx === selectedIdx;
              const isCorrect = isAnswered && idx === correctIdx;
              const isWrong = isSelected && !isCorrect;

              let stateClass = "bg-white border-wax hover:border-honey/50 hover:bg-honey/5 cursor-pointer text-bee-black/80";
              if (isAnswered) {
                if (idx === correctIdx) stateClass = "bg-green-50 border-green-200 text-green-800 ring-2 ring-green-500/20";
                else if (isSelected) stateClass = "bg-red-50 border-red-200 text-red-800";
                else stateClass = "bg-gray-50 border-gray-100 text-gray-400 cursor-not-allowed opacity-60";
              }

              return (
                <button
                  key={idx}
                  disabled={isAnswered}
                  onClick={() => handleSelect(currentIndex, idx)}
                  className={cn(
                    "w-full text-left p-6 rounded-2xl border-2 transition-all duration-200 flex items-center justify-between group relative overflow-hidden shadow-sm",
                    stateClass
                  )}
                >
                  <div className="flex items-center gap-6 relative z-10">
                    <span className={cn(
                      "w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors",
                      isCorrect ? "bg-green-500 text-white border-green-500" :
                        isWrong ? "bg-red-500 text-white border-red-500" :
                          "border-bee-black/10 text-bee-black/40 group-hover:border-honey group-hover:text-honey bg-white"
                    )}>
                      {String.fromCharCode(65 + idx)}
                    </span>
                    <span className="font-medium text-lg leading-snug"><MathTextInline>{opt}</MathTextInline></span>
                  </div>
                  {isCorrect && <CheckCircle2 className="text-green-600 animate-in zoom-in spin-in-180 duration-300" />}
                  {isWrong && <XCircle className="text-red-500 animate-in zoom-in duration-300" />}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function NotesRenderer({ data, artifactId }: { data: any, artifactId: string }) {
  const [isEditing, setIsEditing] = useState(false);
  const [content, setContent] = useState(data.markdown || data.content || "");
  const [isSaving, setIsSaving] = useState(false);

  // Parse markdown to ensure it's a string
  const markdownContent = typeof content === 'string' ? content : "No content available.";

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await api.artifacts.update(artifactId, { content: { ...data, markdown: content } });
      toast.success("Notes saved successfully");
      setIsEditing(false);
    } catch (error) {
      console.error("Failed to save notes:", error);
      toast.error("Failed to save notes");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="h-full flex flex-col relative w-full pt-6 bg-white">
      <div className="px-10 flex justify-between items-center mb-6 shrink-0">
        <div>
          <h2 className="text-3xl font-serif font-bold text-bee-black">Study Notes</h2>
          <p className="text-sm font-medium text-bee-black/40 uppercase tracking-widest mt-1">
            Generated from Knowledge Core
          </p>
        </div>
        <div className="flex gap-3">
          {isEditing ? (
            <>
              <Button
                variant="ghost"
                onClick={() => setIsEditing(false)}
                className="rounded-xl hover:bg-gray-100 font-bold uppercase tracking-widest text-[10px]"
              >
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                className="bg-bee-black text-white hover:bg-honey hover:text-bee-black rounded-xl font-bold uppercase tracking-widest text-[10px] min-w-[100px]"
                disabled={isSaving}
              >
                {isSaving ? <RefreshCw className="animate-spin w-4 h-4" /> : "Save Changes"}
              </Button>
            </>
          ) : (
            <Button
              onClick={() => setIsEditing(true)}
              className="bg-white border border-wax text-bee-black hover:bg-honey/10 rounded-xl font-bold uppercase tracking-widest text-[10px]"
            >
              Edit Notes
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-hidden relative px-10 pb-10">
        {isEditing ? (
          <div className="h-full border border-wax rounded-2xl overflow-hidden shadow-sm" data-color-mode="light">
            <MDEditor
              value={content}
              onChange={(val) => setContent(val || "")}
              height="100%"
              preview="edit"
              className="!border-none !h-full"
              visibleDragbar={false}
            />
          </div>
        ) : (
          <div className="h-full overflow-y-auto custom-scrollbar">
            <div className="max-w-4xl mx-auto bg-white p-12 shadow-sm min-h-full prose prose-lg prose-headings:font-serif prose-headings:text-bee-black text-bee-black/80">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex]}
                components={MarkdownRenderers}
              >
                {markdownContent}
              </ReactMarkdown>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SlidesRenderer({ data, artifact }: { data: any; artifact: Artifact | null }) {
  const [viewMode, setViewMode] = useState<'slides' | 'pptx'>('slides');
  const [pptxSignedUrl, setPptxSignedUrl] = useState<string | null>(null);
  const [pptxLoading, setPptxLoading] = useState(false);

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

  const handleViewPPTX = async () => {
    setViewMode('pptx');
    if (pptxSignedUrl) return;

    if (!artifact?.id || !binaryInfo?.available) return;

    setPptxLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: HeadersInit = {};
      if (session) {
        headers["Authorization"] = `Bearer ${session.access_token}`;
      }

      const res = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download?inline=true`, {
        headers
      });
      if (res.ok) {
        const data = await res.json();
        if (data.download_url) {
          setPptxSignedUrl(data.download_url);
        }
      }
    } catch (err) {
      console.error('[PPTX] Failed to fetch signed URL:', err);
    } finally {
      setPptxLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-bee-black">{data.title || 'Slides'}</h2>
          <p className="text-sm text-bee-black/50">{data.slides.length} slides • {data.audience_level || 'General'} level</p>
        </div>
        <div className="flex gap-2">
          {binaryInfo?.available && (
            <div className="flex bg-cream rounded-xl p-1 border border-wax">
              <button
                onClick={() => setViewMode('slides')}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${viewMode === 'slides'
                  ? 'bg-white shadow text-bee-black'
                  : 'text-bee-black/50 hover:text-bee-black'
                  }`}
              >
                Slides
              </button>
              <button
                onClick={handleViewPPTX}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${viewMode === 'pptx'
                  ? 'bg-white shadow text-bee-black'
                  : 'text-bee-black/50 hover:text-bee-black'
                  }`}
              >
                PPTX Preview
              </button>
            </div>
          )}

          <Button variant="outline" onClick={downloadJSON}>JSON</Button>

          {binaryInfo?.available && (
            <Button
              onClick={handleDownloadPPTX}
              className="bg-bee-black text-white hover:bg-honey hover:text-bee-black"
            >
              <FileText className="w-4 h-4 mr-2" /> Download PPTX
            </Button>
          )}
        </div>
      </div>

      {/* PPTX Preview Mode */}
      {viewMode === 'pptx' && (
        <div className="bg-white rounded-2xl border border-wax overflow-hidden h-[60vh] flex items-center justify-center relative">
          {pptxLoading ? (
            <div className="text-bee-black/50 text-sm">Loading Preview...</div>
          ) : pptxSignedUrl ? (
            <iframe
              src={`https://docs.google.com/viewer?url=${encodeURIComponent(pptxSignedUrl)}&embedded=true`}
              className="w-full h-full border-0"
              title="PPTX Preview"
            />
          ) : (
            <div className="text-bee-black/50 text-sm">Preview not available</div>
          )}
        </div>
      )}

      {/* Slides Mode */}
      {viewMode === 'slides' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.slides.map((slide: any, i: number) => (
            <div
              key={i}
              className="bg-white p-6 rounded-2xl border border-wax aspect-video flex flex-col transition-all hover:shadow-lg hover:-translate-y-1 hover:border-honey cursor-pointer group"
            >
              <h3 className="font-bold text-bee-black mb-2 group-hover:text-honey transition-colors">{stripMarkdown(slide.heading)}</h3>
              <p className="text-sm text-bee-black/60 mb-3">{stripMarkdown(slide.main_idea)}</p>
              <ul className="text-xs space-y-1 flex-1">
                {slide.bullet_points?.slice(0, 4).map((bp: string, b: number) => (
                  <li key={b} className="flex items-start gap-2">
                    <span className="text-honey">•</span>
                    {stripMarkdown(bp)}
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between mt-2">
                <div className="text-[10px] text-bee-black/30">Slide {i + 1}</div>
                <div className="text-[8px] text-bee-black/20 opacity-0 group-hover:opacity-100 transition-opacity">
                  {slide.visual_cue && `📷 ${slide.visual_cue.slice(0, 20)}...`}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FlashcardRenderer({ data }: { data: any }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);

  if (!data?.flashcards) return <EmptyState message="No flashcards data" />;

  const currentCard = data.flashcards[currentIndex];
  const total = data.flashcards.length;

  const handleNext = () => {
    setIsFlipped(false);
    setTimeout(() => setCurrentIndex((c) => (c + 1) % total), 150);
  };

  const handlePrev = () => {
    setIsFlipped(false);
    setTimeout(() => setCurrentIndex((c) => (c - 1 + total) % total), 150);
  };

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') handleNext();
      if (e.key === 'ArrowLeft') handlePrev();
      if (e.key === ' ' || e.key === 'Enter') setIsFlipped(f => !f);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentIndex, total, handleNext, handlePrev]);

  return (
    <div className="h-full flex flex-col items-center justify-center p-8 bg-cream/30">
      <div className="w-full max-w-3xl aspect-[3/2] relative perspective-1000">
        <div
          className={cn(
            "w-full h-full relative preserve-3d transition-all duration-700 cursor-pointer shadow-2xl rounded-[3rem]",
            isFlipped ? "rotate-y-180" : ""
          )}
          onClick={() => setIsFlipped(!isFlipped)}
        >
          {/* Front (Black/Gold) */}
          <div className="absolute inset-0 backface-hidden bg-bee-black text-white rounded-[3rem] p-12 flex flex-col items-center justify-center border border-white/10 shadow-[0_20px_50px_-12px_rgba(0,0,0,0.5)]">
            <div className="absolute top-8 left-8">
              <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-honey/60">Front</span>
            </div>
            <div className="absolute top-8 right-8">
              <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-white/20">{currentIndex + 1} / {total}</span>
            </div>

            <div className="flex-1 flex items-center justify-center w-full">
              <h3 className="text-3xl md:text-4xl font-serif font-bold text-center leading-tight">
                <MathText>{currentCard.front}</MathText>
              </h3>
            </div>

            <p className="text-white/20 text-xs uppercase tracking-widest mt-auto">Click to reveal</p>
          </div>

          {/* Back (White/Gold) */}
          <div className="absolute inset-0 backface-hidden rotate-y-180 bg-white text-bee-black rounded-[3rem] p-12 flex flex-col items-center justify-center border border-wax shadow-xl">
            <div className="absolute top-8 left-8">
              <span className="text-[10px] font-bold uppercase tracking-[0.3em] text-honey">Back</span>
            </div>

            <div className="flex-1 flex items-center justify-center w-full overflow-y-auto custom-scrollbar">
              <div className="text-xl md:text-2xl font-serif font-medium text-center leading-relaxed text-bee-black/80">
                <MathText>{currentCard.back}</MathText>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="mt-12 flex items-center gap-8">
        <Button
          onClick={handlePrev}
          variant="outline"
          size="icon"
          className="w-14 h-14 rounded-full border-2 border-bee-black/10 hover:border-bee-black/30 hover:bg-white text-bee-black/60"
        >
          <ChevronLeft size={24} />
        </Button>

        <span className="font-mono text-sm font-bold text-bee-black/30 tracking-widest">
          {currentIndex + 1} <span className="mx-2 opacity-30">/</span> {total}
        </span>

        <Button
          onClick={handleNext}
          variant="outline"
          size="icon"
          className="w-14 h-14 rounded-full border-2 border-bee-black/10 hover:border-bee-black/30 hover:bg-white text-bee-black/60"
        >
          <ChevronRight size={24} />
        </Button>
      </div>
    </div>
  );
}

function ExamRenderer({ data, artifact }: { data: any; artifact: Artifact | null }) {
  const [showAnswers, setShowAnswers] = useState(false);
  const [viewMode, setViewMode] = useState<'questions' | 'pdf'>('questions');
  const [pdfSignedUrl, setPdfSignedUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const binaryInfo = getBinaryInfo(artifact);

  if (!data?.questions || data.questions.length === 0) {
    return <EmptyState message="No exam questions generated" />;
  }

  const handleDownloadPDF = () => {
    if (artifact?.id) {
      downloadBinary(artifact.id, 'final_exam.pdf');
    }
  };

  // Fetch signed URL when switching to PDF view
  const handleViewPDF = async () => {
    setViewMode('pdf');
    if (pdfSignedUrl) return; // Already have URL

    if (!artifact?.id || !binaryInfo?.available) return;

    setPdfLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: HeadersInit = {};
      if (session) {
        headers["Authorization"] = `Bearer ${session.access_token}`;
      }

      const res = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download?inline=true`, {
        headers
      });
      if (res.ok) {
        const data = await res.json();
        if (data.download_url) {
          setPdfSignedUrl(data.download_url);
        }
      }
    } catch (err) {
      console.error('[PDF] Failed to fetch signed URL:', err);
    } finally {
      setPdfLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-bee-black">{data.title || 'Final Exam'}</h2>
        <div className="flex gap-2">
          {/* View Mode Toggle */}
          {binaryInfo?.available && (
            <div className="flex bg-cream rounded-xl p-1 border border-wax">
              <button
                onClick={() => setViewMode('questions')}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${viewMode === 'questions'
                  ? 'bg-white shadow text-bee-black'
                  : 'text-bee-black/50 hover:text-bee-black'
                  }`}
              >
                Questions
              </button>
              <button
                onClick={handleViewPDF}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${viewMode === 'pdf'
                  ? 'bg-white shadow text-bee-black'
                  : 'text-bee-black/50 hover:text-bee-black'
                  }`}
              >
                PDF Preview
              </button>
            </div>
          )}
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

      {/* PDF Preview Mode */}
      {viewMode === 'pdf' && (
        <div className="bg-white rounded-2xl border border-wax overflow-hidden h-[60vh] flex items-center justify-center">
          {pdfLoading ? (
            <div className="text-bee-black/50 text-sm">Loading PDF...</div>
          ) : pdfSignedUrl ? (
            <object
              data={pdfSignedUrl}
              type="application/pdf"
              className="w-full h-full"
            >
              {/* Fallback if object tag doesn't work */}
              <iframe
                src={pdfSignedUrl}
                className="w-full h-full"
                title="PDF Preview"
              />
            </object>
          ) : (
            <div className="text-bee-black/50 text-sm">PDF not available</div>
          )}
        </div>
      )}

      {/* Questions Mode */}
      {viewMode === 'questions' && (
        <div className="h-full overflow-y-auto custom-scrollbar px-10 pb-20">
          <div className="max-w-4xl mx-auto space-y-8">
            {data.instructions && (
              <div className="p-6 bg-honey/5 border border-honey/20 rounded-2xl text-sm text-bee-black/80 leading-relaxed font-serif italic relative overflow-hidden">
                <div className="absolute top-0 left-0 w-1 h-full bg-honey" />
                <strong className="block mb-2 text-honey font-sans uppercase tracking-widest text-[10px]">Instructions</strong>
                {data.instructions}
              </div>
            )}

            <div className="space-y-6">
              {data.questions.map((q: any, idx: number) => (
                <div key={q.id || idx} className="bg-white p-8 rounded-[2rem] border border-wax shadow-sm hover:shadow-md transition-all group">
                  <div className="flex items-start justify-between mb-6 border-b border-wax pb-4">
                    <div className="flex items-center gap-4">
                      <span className="flex items-center justify-center w-10 h-10 rounded-full bg-bee-black text-honey font-serif font-bold text-lg shadow-lg shadow-bee-black/10">
                        {idx + 1}
                      </span>
                      <Badge variant="outline" className="border-wax text-bee-black/40 text-[10px] uppercase tracking-widest bg-cream/50">
                        {q.type}
                      </Badge>
                    </div>
                    <Badge className="bg-honey/10 text-honey hover:bg-honey/20 border-none font-bold tabular-nums">
                      {q.points} pts
                    </Badge>
                  </div>

                  <div className="text-xl font-medium text-bee-black/90 leading-relaxed mb-6 font-serif">
                    <MathText>{q.text}</MathText>
                  </div>

                  {q.options && (
                    <div className="space-y-3 pl-4 border-l-2 border-wax group-hover:border-honey/30 transition-colors">
                      {q.options.map((opt: string, i: number) => (
                        <div key={i} className="flex items-center gap-3 text-bee-black/70 hover:text-bee-black transition-colors">
                          <div className="w-6 h-6 rounded-full border border-wax flex items-center justify-center text-[10px] font-bold text-bee-black/30">
                            {String.fromCharCode(65 + i)}
                          </div>
                          <MathTextInline>{opt}</MathTextInline>
                        </div>
                      ))}
                    </div>
                  )}

                  {showAnswers && (
                    <div className="mt-8 pt-6 border-t border-wax animate-in fade-in slide-in-from-top-2">
                      <div className="bg-green-50 border border-green-100 rounded-xl p-5">
                        <div className="flex items-center gap-2 mb-2 text-green-700 font-bold text-xs uppercase tracking-widest">
                          <CheckCircle2 size={14} /> Correct Answer
                        </div>
                        <div className="text-green-900 font-medium">
                          {q.options ? q.options[q.correct_answer_index] : q.correct_answer}
                        </div>
                        {q.explanation && (
                          <div className="mt-3 text-green-800/70 text-sm leading-relaxed border-t border-green-200/50 pt-3">
                            {q.explanation}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
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
      case 'quiz': return <QuizRenderer data={data} />;
      case 'notes': return <NotesRenderer data={data} artifactId={artifact.id} />;
      case 'slides': return <SlidesRenderer data={data} artifact={artifact} />;
      case 'flashcards': return <FlashcardRenderer data={data} />;
      case 'exam': return <ExamRenderer data={data} artifact={artifact} />;
      case 'knowledge_core': return <KnowledgeCoreRenderer data={data} />;
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
      <DialogContent
        className="
          fixed left-[50%] top-[50%] translate-x-[-50%] translate-y-[-50%]
          w-[95vw] max-w-5xl h-[90vh] max-h-[90vh]
          rounded-[32px] border border-white/20 bg-cream/80 backdrop-blur-2xl
          p-0 shadow-2xl z-[100] flex flex-col overflow-hidden outline-none
        "
      >
        <DialogTitle className="sr-only">
          {artifact?.content?.title || artifact?.content?.original_name || artifact?.type || 'Artifact Preview'}
        </DialogTitle>

        {/* Header - Fixed Height, shrinking */}
        <div className="shrink-0 z-10 bg-cream/95 backdrop-blur-xl border-b border-wax p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-bee-black/5 rounded-2xl border border-wax">
              <Icon size={24} className="text-bee-black" />
            </div>
            <div>
              <h2 className="text-lg font-bold font-serif text-bee-black uppercase tracking-wide">
                {artifact?.content?.title || label}
              </h2>
              <div className="flex items-center gap-3 mt-1">
                <Badge variant="outline" className="bg-white border-wax text-bee-black/40 text-[9px] uppercase tracking-widest px-2 py-0.5 h-5">
                  {artifactType}
                </Badge>
                <span className="text-[10px] font-bold text-bee-black/20 uppercase tracking-widest">
                  Generated via BeePrepared
                </span>
              </div>
            </div>
          </div>

          <div className="flex gap-2">
            {onRegenerate && (
              <Button
                variant="ghost"
                onClick={onRegenerate}
                disabled={isRegenerating}
                className="gap-2"
              >
                <RefreshCw className={`w-4 h-4 ${isRegenerating ? 'animate-spin' : ''}`} />
                {isRegenerating ? 'Regenerating...' : 'Regenerate'}
              </Button>
            )}
          </div>
        </div>

        {/* Content - Flexible, scrolling */}
        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
          <div className="mx-auto max-w-3xl">
            {renderContent()}
          </div>
        </div>

        {/* Footer - Fixed Height, shrinking */}
        <div className="shrink-0 bg-cream/95 backdrop-blur-xl border-t border-wax p-4 flex justify-between items-center">
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
