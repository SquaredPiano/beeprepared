"use client";

import React, { useState, useMemo, useEffect, useCallback } from "react";
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
    <h1 className="text-3xl md:text-4xl font-sans font-bold text-bee-black mb-6 mt-8 pb-4 border-b-2 border-honey/20 first:mt-0 tracking-tight">
      {children}
    </h1>
  ),
  h2: ({ children }: any) => (
    <h2 className="text-2xl md:text-3xl font-sans font-bold text-bee-black mb-4 mt-8 flex items-center gap-2 tracking-tight">
      <span className="w-2 h-8 bg-honey rounded-full block" />
      {children}
    </h2>
  ),
  h3: ({ children }: any) => (
    <h3 className="text-xl md:text-2xl font-sans font-semibold text-bee-black/80 mb-3 mt-6 tracking-tight">
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

  // Helper to ensure we don't strip the root key
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const _wrap = (key: string, data: Record<string, unknown>) => {
    if (!data) return null;
    if (data[key]) return data;
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
      if (notesData?.body) return { markdown: notesData.body };
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
    const { data: { session } } = await supabase.auth.getSession();
    const headers: HeadersInit = {};
    if (session) {
      headers["Authorization"] = `Bearer ${session.access_token}`;
    }

    const res = await fetch(`${API_BASE}/api/artifacts/${artifactId}/download`, { headers });
    if (!res.ok) {
      const errText = await res.text();
      console.error('[Download] Error response:', errText);
      throw new Error(`HTTP ${res.status}: ${errText}`);
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
    toast.error('Download failed. The file may not be ready yet.');
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
  const _answeredCount = Object.keys(answers).length; // eslint-disable-line @typescript-eslint/no-unused-vars
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

  // Quiz UI - Apple/Clean Style
  return (
    <div className="h-full bg-[#FAFAFA] text-bee-black flex flex-col">
      {/* Header */}
      <div className="p-8 pb-4 shrink-0 flex items-center justify-between border-b border-black/5 bg-white/50 backdrop-blur-md sticky top-0 z-10">
        <div className="text-xs font-bold uppercase tracking-[0.2em] text-black/40">
          Question {currentIndex + 1} of {total}
        </div>
        <div className="flex gap-1.5">
          {data.questions.map((_: any, idx: number) => (
            <div
              key={idx}
              className={cn(
                "h-1.5 rounded-full transition-all duration-300",
                idx === currentIndex ? "w-8 bg-black shadow-sm" :
                  idx < currentIndex ? (answers[idx] === data.questions[idx].correct_answer_index ? "w-2 bg-green-500" : "w-2 bg-red-400") :
                    "w-2 bg-black/5"
              )}
            />
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="max-w-3xl mx-auto p-8 md:p-12 pb-24">
          <h3 className="text-3xl md:text-4xl font-serif font-bold leading-tight mb-12 text-black tracking-tight">
            <MathText>{currentQuestion.text}</MathText>
          </h3>

          <div className="space-y-4">
            {currentQuestion.options?.map((opt: string, idx: number) => {
              const isSelected = isAnswered && idx === selectedIdx;
              const isCorrect = isAnswered && idx === correctIdx;
              const isWrong = isSelected && !isCorrect;

              let containerClass = "bg-white border-black/5 shadow-sm hover:border-black/20 hover:shadow-md active:scale-[0.99]";
              let textClass = "text-black/80 font-medium";
              let markerClass = "border-black/10 text-black/40 bg-black/5";

              if (isAnswered) {
                containerClass = "opacity-50 cursor-not-allowed border-transparent shadow-none bg-gray-50";

                if (idx === correctIdx) {
                  containerClass = "bg-green-50 border-green-200 shadow-sm opacity-100 ring-1 ring-green-500/20";
                  textClass = "text-green-800 font-semibold";
                  markerClass = "bg-green-100 text-green-700 border-green-200";
                } else if (isSelected) {
                  containerClass = "bg-red-50 border-red-100 shadow-sm opacity-100";
                  textClass = "text-red-800";
                  markerClass = "bg-red-100 text-red-700 border-red-200";
                }
              } else if (idx === selectedIdx) {
                // Selection state before confirming (if we had a confirm step, but we select immediately)
              }

              return (
                <button
                  key={idx}
                  disabled={isAnswered}
                  onClick={() => handleSelect(currentIndex, idx)}
                  className={cn(
                    "w-full text-left p-6 rounded-2xl border transition-all duration-200 flex items-center gap-6 group relative overflow-hidden",
                    containerClass
                  )}
                >
                  <span className={cn(
                    "w-10 h-10 shrink-0 rounded-full flex items-center justify-center text-sm font-bold border transition-colors",
                    markerClass,
                    !isAnswered && "group-hover:bg-black group-hover:text-white group-hover:border-black"
                  )}>
                    {String.fromCharCode(65 + idx)}
                  </span>
                  <span className={cn("text-lg flex-1", textClass)}>
                    <MathTextInline>{opt}</MathTextInline>
                  </span>

                  {isCorrect && <CheckCircle2 className="text-green-600 shrink-0" />}
                  {isWrong && <XCircle className="text-red-500 shrink-0" />}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// Helper to clean markdown that might be wrapped in code blocks
function cleanMarkdownForDisplay(content: string): string {
  if (!content) return "";
  let clean = content.trim();
  // Remove wrapping ```markdown ... ``` or ``` ... ```
  if (clean.startsWith('```') && clean.endsWith('```')) {
    const lines = clean.split('\n');
    if (lines.length >= 2) {
      // Remove first and last lines
      clean = lines.slice(1, -1).join('\n');
    }
  }
  return clean;
}

function NotesRenderer({ data, artifactId, onUpdate }: { data: any, artifactId: string, onUpdate?: (a: Artifact) => void }) {
  const [isEditing, setIsEditing] = useState(false);
  const [content, setContent] = useState(data.markdown || data.content || data.body || "");
  const [isSaving, setIsSaving] = useState(false);

  // Parse and clean markdown
  const rawContent = typeof content === 'string' ? content : "No content available.";
  const markdownContent = useMemo(() => cleanMarkdownForDisplay(rawContent), [rawContent]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const newArtifact = await api.artifacts.update(artifactId, { content: { ...data, markdown: content, body: content } });
      if (onUpdate) onUpdate(
        newArtifact // The parent will handle the update
      );
      setIsEditing(false);
      toast.success("Notes saved successfully");
    } catch (error) {
      console.error("Failed to save notes:", error);
      toast.error("Failed to save notes");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="shrink-0 px-8 py-5 border-b border-gray-100 bg-white flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-serif font-bold text-gray-900">{data.title || 'Study Notes'}</h2>
          <p className="text-sm text-gray-500 mt-1">
            AI-generated comprehensive study material
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isEditing ? (
            <>
              <Button
                variant="ghost"
                onClick={() => setIsEditing(false)}
                className="rounded-full text-gray-600 hover:bg-gray-100 px-4"
              >
                Cancel
              </Button>
              <Button
                onClick={handleSave}
                className="bg-gray-900 text-white hover:bg-gray-800 rounded-full px-5 gap-2"
                disabled={isSaving}
              >
                {isSaving ? <RefreshCw className="animate-spin w-4 h-4" /> : "Save Changes"}
              </Button>
            </>
          ) : (
            <Button
              onClick={() => setIsEditing(true)}
              variant="outline"
              className="rounded-full border-gray-200 text-gray-700 hover:bg-gray-50 px-4"
            >
              Edit Notes
            </Button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {isEditing ? (
          <div className="h-full p-6" data-color-mode="light">
            <div className="h-full border border-gray-200 rounded-xl overflow-hidden shadow-sm bg-white">
              <MDEditor
                value={content}
                onChange={(val) => setContent(val || "")}
                height="100%"
                preview="edit"
                className="!border-none !h-full"
                visibleDragbar={false}
              />
            </div>
          </div>
        ) : (
          <div className="h-full overflow-y-auto bg-white custom-scrollbar">
            <div className="max-w-5xl mx-auto py-12 px-8 md:px-16">
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
  const binaryInfo = getBinaryInfo(artifact);

  const handleDownloadPPTX = () => {
    if (!binaryInfo?.available) {
      toast.error('PPTX not yet generated. Please wait.');
      return;
    }
    if (artifact?.id) {
      downloadBinary(artifact.id, 'slides.pptx');
    }
  };

  const handleViewPPTX = useCallback(async () => {
    setViewMode('pptx');
    if (pptxSignedUrl) return;
    if (!artifact?.id) return;

    setPptxLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: HeadersInit = {};
      if (session) {
        headers["Authorization"] = `Bearer ${session.access_token}`;
      }
      const res = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download?inline=true`, { headers });
      if (res.ok) {
        const resData = await res.json();
        if (resData.download_url) {
          setPptxSignedUrl(resData.download_url);
        }
      }
    } catch (err) {
      console.error('[PPTX] Failed to fetch signed URL:', err);
    } finally {
      setPptxLoading(false);
    }
  }, [pptxSignedUrl, artifact?.id]);

  useEffect(() => {
    if (binaryInfo?.available && artifact?.id && viewMode === 'slides' && !pptxSignedUrl) {
      handleViewPPTX();
    }
  }, [binaryInfo?.available, artifact?.id, viewMode, pptxSignedUrl, handleViewPPTX]);

  if (!data?.slides) return <EmptyState message="No slides data" />;

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header */}
      <div className="shrink-0 px-8 py-5 border-b border-gray-100 bg-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-serif font-bold text-gray-900">{data.title || 'Presentation'}</h2>
            <p className="text-sm text-gray-500 mt-1">
              {data.slides.length} slides • {data.audience_level || 'General'} level
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Toggle Slider */}
            <div className="relative flex bg-gray-100 rounded-full p-1">
              <div
                className={cn(
                  "absolute top-1 bottom-1 rounded-full bg-white shadow-sm transition-all duration-200 ease-out",
                  viewMode === 'slides' ? "left-1 w-[60px]" : "left-[65px] w-[100px]"
                )}
              />
              <button
                onClick={() => setViewMode('slides')}
                className={cn(
                  "relative z-10 px-4 py-1.5 text-xs font-semibold rounded-full transition-colors",
                  viewMode === 'slides' ? 'text-gray-900' : 'text-gray-500 hover:text-gray-700'
                )}
              >
                Slides
              </button>
              <button
                onClick={handleViewPPTX}
                className={cn(
                  "relative z-10 px-4 py-1.5 text-xs font-semibold rounded-full transition-colors",
                  viewMode === 'pptx' ? 'text-gray-900' : 'text-gray-500 hover:text-gray-700'
                )}
              >
                PPTX Preview
              </button>
            </div>

            {/* Download Button */}
            {binaryInfo?.available ? (
              <Button
                onClick={handleDownloadPPTX}
                size="sm"
                className="bg-gray-900 text-white hover:bg-gray-800 rounded-full px-4 gap-2"
              >
                <Presentation className="w-4 h-4" /> Download PPTX
              </Button>
            ) : (
              <Button variant="ghost" size="sm" disabled className="text-gray-400 rounded-full px-4 gap-2">
                <RefreshCw className="w-4 h-4 animate-spin" /> Generating...
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {/* PPTX Preview Mode */}
        {viewMode === 'pptx' && (
          <div className="h-full w-full bg-gray-50 flex flex-col p-4 md:p-8">
            {pptxLoading ? (
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-500">
                <RefreshCw className="w-6 h-6 animate-spin" />
                <span className="text-sm">Loading preview...</span>
              </div>
            ) : pptxSignedUrl ? (
              <div className="flex-1 w-full max-w-6xl mx-auto bg-white rounded-xl shadow-lg border border-gray-200 overflow-hidden relative">
                <iframe
                  src={`https://docs.google.com/viewer?url=${encodeURIComponent(pptxSignedUrl)}&embedded=true`}
                  className="w-full h-full border-0 block"
                  title="PPTX Preview"
                />
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-400">
                <Presentation className="w-10 h-10" />
                <span className="text-sm">Preview not available</span>
              </div>
            )}
          </div>
        )}

        {/* Slides Grid Mode */}
        {viewMode === 'slides' && (
          <div className="p-8">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {data.slides.map((slide: any, i: number) => (
                <div
                  key={i}
                  className="group bg-white rounded-xl border border-gray-200 overflow-hidden hover:border-gray-300 hover:shadow-md transition-all"
                >
                  {/* Slide Header */}
                  <div className="bg-gray-50 px-4 py-3 border-b border-gray-100 flex items-center justify-between">
                    <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">
                      Slide {i + 1}
                    </span>
                  </div>
                  {/* Slide Content - 16:9 aspect ratio */}
                  <div className="aspect-video p-5 flex flex-col">
                    <h3 className="font-semibold text-gray-900 text-sm mb-2 line-clamp-2 group-hover:text-blue-600 transition-colors">
                      {stripMarkdown(slide.heading)}
                    </h3>
                    {slide.main_idea && (
                      <p className="text-xs text-gray-500 mb-3 italic line-clamp-2">
                        {stripMarkdown(slide.main_idea)}
                      </p>
                    )}
                    <ul className="text-xs text-gray-600 space-y-1 flex-1">
                      {slide.bullet_points?.slice(0, 3).map((bp: string, b: number) => (
                        <li key={b} className="flex items-start gap-2">
                          <span className="text-blue-500 mt-0.5">•</span>
                          <span className="line-clamp-1">{stripMarkdown(bp)}</span>
                        </li>
                      ))}
                      {slide.bullet_points?.length > 3 && (
                        <li className="text-gray-400 text-[10px]">
                          +{slide.bullet_points.length - 3} more
                        </li>
                      )}
                    </ul>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function FlashcardRenderer({ data }: { data: any }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);

  const total = data?.flashcards?.length || 0;

  const handleNext = useCallback(() => {
    if (!total) return;
    setIsFlipped(false);
    setTimeout(() => setCurrentIndex((c) => (c + 1) % total), 150);
  }, [total]);

  const handlePrev = useCallback(() => {
    if (!total) return;
    setIsFlipped(false);
    setTimeout(() => setCurrentIndex((c) => (c - 1 + total) % total), 150);
  }, [total]);

  useEffect(() => {
    if (!total) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight') handleNext();
      if (e.key === 'ArrowLeft') handlePrev();
      if (e.key === ' ' || e.key === 'Enter') setIsFlipped(f => !f);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleNext, handlePrev, total]);

  if (!data?.flashcards || total === 0) return <EmptyState message="No flashcards data" />;

  const currentCard = data.flashcards[currentIndex];

  return (
    <div className="h-full flex flex-col bg-gradient-to-b from-gray-50 to-gray-100">
      {/* Header */}
      <div className="shrink-0 px-8 py-5 bg-white border-b border-gray-100">
        <div className="flex items-center justify-between max-w-3xl mx-auto">
          <div>
            <h2 className="text-xl font-serif font-bold text-gray-900">Flashcards</h2>
            <p className="text-sm text-gray-500 mt-0.5">{total} cards • Use arrow keys to navigate</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-600 tabular-nums bg-gray-100 px-3 py-1 rounded-full">
              {currentIndex + 1} / {total}
            </span>
          </div>
        </div>
      </div>

      {/* Card Area */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-2xl aspect-[4/3] relative perspective-[1000px]">
          <div
            className={cn(
              "w-full h-full relative cursor-pointer transition-all duration-500 ease-out",
              isFlipped ? "[transform:rotateY(180deg)]" : ""
            )}
            onClick={() => setIsFlipped(!isFlipped)}
            style={{ transformStyle: 'preserve-3d' }}
          >
            {/* Front */}
            <div
              className="absolute inset-0 bg-white rounded-3xl p-10 flex flex-col items-center justify-center border border-gray-200 shadow-xl"
              style={{ backfaceVisibility: 'hidden' }}
            >
              <div className="absolute top-6 left-6 right-6 flex items-center justify-between">
                <span className="text-[10px] font-bold uppercase tracking-widest text-blue-600">Question</span>
                <span className="text-[10px] font-bold uppercase tracking-widest text-gray-300">
                  {currentIndex + 1} / {total}
                </span>
              </div>

              <div className="flex-1 flex items-center justify-center w-full">
                <h3 className="text-2xl md:text-3xl font-serif font-bold text-gray-900 text-center leading-snug">
                  <MathText>{currentCard.front}</MathText>
                </h3>
              </div>

              <p className="text-gray-400 text-xs font-medium mt-auto">Tap to reveal answer</p>
            </div>

            {/* Back */}
            <div
              className="absolute inset-0 bg-gray-900 rounded-3xl p-10 flex flex-col items-center justify-center shadow-xl force-white-text [transform:rotateY(180deg)]"
              style={{ backfaceVisibility: 'hidden' }}
            >
              <div className="absolute top-6 left-6">
                <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-400">Answer</span>
              </div>

              <div className="flex-1 flex items-center justify-center w-full overflow-y-auto">
                <div className="text-xl md:text-2xl font-serif font-medium text-center leading-relaxed" style={{ color: 'white' }}>
                  <MathText>{currentCard.back}</MathText>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="shrink-0 py-6 bg-white border-t border-gray-100">
        <div className="flex items-center justify-center gap-6">
          <Button
            onClick={handlePrev}
            variant="outline"
            size="icon"
            className="w-12 h-12 rounded-full border-gray-200 hover:bg-gray-50"
          >
            <ChevronLeft size={20} className="text-gray-600" />
          </Button>

          {/* Progress dots */}
          <div className="flex items-center gap-1.5">
            {Array.from({ length: Math.min(total, 10) }).map((_, i) => (
              <div
                key={i}
                className={cn(
                  "w-2 h-2 rounded-full transition-colors",
                  i === currentIndex ? "bg-gray-900" : "bg-gray-200"
                )}
              />
            ))}
            {total > 10 && <span className="text-xs text-gray-400 ml-1">+{total - 10}</span>}
          </div>

          <Button
            onClick={handleNext}
            variant="outline"
            size="icon"
            className="w-12 h-12 rounded-full border-gray-200 hover:bg-gray-50"
          >
            <ChevronRight size={20} className="text-gray-600" />
          </Button>
        </div>
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

  const handleViewPDF = async () => {
    setViewMode('pdf');
    if (pdfSignedUrl) return;
    if (!artifact?.id) return;

    setPdfLoading(true);
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const headers: HeadersInit = {};
      if (session) {
        headers["Authorization"] = `Bearer ${session.access_token}`;
      }
      const res = await fetch(`${API_BASE}/api/artifacts/${artifact.id}/download?inline=true`, { headers });
      if (res.ok) {
        const resData = await res.json();
        if (resData.download_url) {
          setPdfSignedUrl(resData.download_url);
        }
      }
    } catch (err) {
      console.error('[PDF] Failed to fetch signed URL:', err);
    } finally {
      setPdfLoading(false);
    }
  };

  const totalPoints = data.questions.reduce((sum: number, q: any) => sum + (q.points || 0), 0);

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Header Bar */}
      <div className="shrink-0 px-8 py-5 border-b border-gray-100 bg-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-serif font-bold text-gray-900">{data.title || 'Final Exam'}</h2>
            <p className="text-sm text-gray-500 mt-1">
              {data.questions.length} questions • {totalPoints} points total
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Polished Toggle Slider */}
            <div className="relative flex bg-gray-100 rounded-full p-1">
              <div
                className={cn(
                  "absolute top-1 bottom-1 rounded-full bg-white shadow-sm transition-all duration-200 ease-out",
                  viewMode === 'questions' ? "left-1 w-[90px]" : "left-[95px] w-[100px]"
                )}
              />
              <button
                onClick={() => setViewMode('questions')}
                className={cn(
                  "relative z-10 px-4 py-1.5 text-xs font-semibold rounded-full transition-colors",
                  viewMode === 'questions' ? 'text-gray-900' : 'text-gray-500 hover:text-gray-700'
                )}
              >
                Questions
              </button>
              <button
                onClick={handleViewPDF}
                className={cn(
                  "relative z-10 px-4 py-1.5 text-xs font-semibold rounded-full transition-colors",
                  viewMode === 'pdf' ? 'text-gray-900' : 'text-gray-500 hover:text-gray-700'
                )}
              >
                PDF Preview
              </button>
            </div>

            {/* Show/Hide Answers Toggle */}
            <button
              onClick={() => setShowAnswers(!showAnswers)}
              className={cn(
                "px-4 py-2 text-xs font-semibold rounded-full border transition-all",
                showAnswers
                  ? "bg-emerald-50 border-emerald-200 text-emerald-700"
                  : "bg-white border-gray-200 text-gray-600 hover:border-gray-300"
              )}
            >
              {showAnswers ? '✓ Answers Visible' : 'Show Answers'}
            </button>

            {/* Download Button */}
            {binaryInfo?.available ? (
              <Button
                onClick={handleDownloadPDF}
                size="sm"
                className="bg-gray-900 text-white hover:bg-gray-800 rounded-full px-4 gap-2"
              >
                <FileText className="w-4 h-4" /> Download PDF
              </Button>
            ) : (
              <Button variant="ghost" size="sm" disabled className="text-gray-400 rounded-full px-4 gap-2">
                <RefreshCw className="w-4 h-4 animate-spin" /> Generating...
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-y-auto">
        {/* PDF Preview Mode */}
        {viewMode === 'pdf' && (
          <div className="h-full w-full bg-gray-50 flex flex-col p-4 md:p-8">
            {pdfLoading ? (
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-500">
                <RefreshCw className="w-6 h-6 animate-spin" />
                <span className="text-sm">Loading PDF...</span>
              </div>
            ) : pdfSignedUrl ? (
              <div className="flex-1 w-full max-w-6xl mx-auto bg-white rounded-xl shadow-lg border border-gray-200 overflow-hidden relative">
                <object data={pdfSignedUrl} type="application/pdf" className="w-full h-full block">
                  <iframe src={pdfSignedUrl} className="w-full h-full border-none block" title="PDF Preview" />
                </object>
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-gray-400">
                <FileText className="w-10 h-10" />
                <span className="text-sm">PDF preview not available</span>
              </div>
            )}
          </div>
        )}

        {/* Questions Mode */}
        {viewMode === 'questions' && (
          <div className="max-w-3xl mx-auto px-8 py-8">
            {/* Instructions */}
            {data.instructions && (
              <div className="mb-8 p-5 bg-amber-50 border border-amber-100 rounded-xl">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-amber-100 rounded-lg flex items-center justify-center shrink-0">
                    <BookOpen className="w-4 h-4 text-amber-600" />
                  </div>
                  <div>
                    <h4 className="font-semibold text-amber-900 text-sm mb-1">Instructions</h4>
                    <p className="text-sm text-amber-800/80 leading-relaxed">{data.instructions}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Questions List */}
            <div className="space-y-6">
              {data.questions.map((q: any, idx: number) => (
                <div
                  key={q.id || idx}
                  className="bg-white border border-gray-200 rounded-2xl overflow-hidden hover:border-gray-300 transition-colors"
                >
                  {/* Question Header */}
                  <div className="px-6 py-4 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gray-900 text-white font-bold text-sm">
                        {idx + 1}
                      </span>
                      <Badge variant="outline" className="text-[10px] uppercase tracking-wider bg-white border-gray-200 text-gray-500">
                        {q.type}
                      </Badge>
                    </div>
                    <span className="text-sm font-semibold text-gray-600 tabular-nums">
                      {q.points} pts
                    </span>
                  </div>

                  {/* Question Body */}
                  <div className="px-6 py-5">
                    <div className="text-base text-gray-800 leading-relaxed mb-5">
                      <MathText>{q.text}</MathText>
                    </div>

                    {/* MCQ Options */}
                    {q.options && q.options.length > 0 && (
                      <div className="space-y-2 ml-2">
                        {q.options.map((opt: string, i: number) => (
                          <div
                            key={i}
                            className="flex items-start gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors"
                          >
                            <span className="w-6 h-6 rounded-full bg-gray-100 text-gray-500 flex items-center justify-center text-xs font-semibold shrink-0">
                              {String.fromCharCode(65 + i)}
                            </span>
                            <span className="text-gray-700 text-sm pt-0.5">
                              <MathTextInline>{opt}</MathTextInline>
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Answer Section (when visible) */}
                    {showAnswers && (
                      <div className="mt-5 pt-5 border-t border-gray-100 animate-in fade-in slide-in-from-top-2 duration-200">
                        <div className="bg-emerald-50 border border-emerald-100 rounded-xl p-5">
                          <div className="flex items-center gap-2 mb-3">
                            <CheckCircle2 size={16} className="text-emerald-600" />
                            <span className="font-semibold text-emerald-800 text-sm">Model Answer</span>
                          </div>
                          <div className="text-emerald-900 leading-relaxed">
                            {/* Exam questions use model_answer field */}
                            {q.model_answer || (q.options && q.options[q.correct_answer_index]) || 'No answer provided'}
                          </div>
                          {/* Grading notes for exam questions */}
                          {q.grading_notes && (
                            <div className="mt-4 pt-4 border-t border-emerald-200/50">
                              <div className="text-xs font-semibold text-emerald-700 uppercase tracking-wider mb-2">Grading Notes</div>
                              <div className="text-sm text-emerald-800/70 leading-relaxed">
                                {q.grading_notes}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
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
  onUpdate?: (newArtifact: Artifact) => void;
}

export function ArtifactPreviewModal({
  isOpen,
  onClose,
  artifact,
  onRegenerate,
  isRegenerating = false,
  onUpdate,
}: ArtifactPreviewModalProps) {
  const artifactType = artifact?.type || 'text';
  const data = useMemo(() => normalizeArtifact(artifactType, artifact), [artifact, artifactType]);

  if (!artifact) return null;

  const Icon = TYPE_ICONS[artifactType] || FileText;
  const label = TYPE_LABELS[artifactType] || artifactType;

  const renderContent = () => {
    switch (artifactType) {
      case 'quiz': return <QuizRenderer data={data} />;
      case 'notes': return <NotesRenderer data={data} artifactId={artifact.id} onUpdate={onUpdate} />;
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

        {/* Content - Flexible, full width/height */}
        <div className="flex-1 overflow-hidden relative bg-white flex flex-col">
          {renderContent()}
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
