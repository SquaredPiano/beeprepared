'use client';

import { useState } from 'react';
import { useJobOrchestrator } from './hooks/useJobOrchestrator';
import './workspace.css';

type SourceType = 'youtube' | 'audio' | 'video' | 'pdf' | 'pptx' | 'md';
type TargetType = 'quiz' | 'notes' | 'slides' | 'flashcards' | 'exam';

const SOURCE_TYPES: { type: SourceType; label: string; placeholder: string }[] = [
    { type: 'youtube', label: '🎬 YouTube', placeholder: 'https://youtube.com/watch?v=...' },
    { type: 'audio', label: '🎵 Audio', placeholder: '/path/to/audio.mp3' },
    { type: 'video', label: '📹 Video', placeholder: '/path/to/video.mp4' },
    { type: 'pdf', label: '📄 PDF', placeholder: '/path/to/document.pdf' },
    { type: 'pptx', label: '📊 PPTX', placeholder: '/path/to/presentation.pptx' },
    { type: 'md', label: '📝 Markdown', placeholder: '/path/to/notes.md' },
];

const TARGETS: { type: TargetType; label: string; icon: string }[] = [
    { type: 'quiz', label: 'Quiz', icon: '❓' },
    { type: 'notes', label: 'Notes', icon: '📝' },
    { type: 'slides', label: 'Slides', icon: '📊' },
    { type: 'flashcards', label: 'Flashcards', icon: '🃏' },
    { type: 'exam', label: 'Exam', icon: '📋' },
];

// ============================================================================
// Text Sanitization - Strip markdown artifacts from LLM output
// ============================================================================
function stripMarkdown(text: string | null | undefined): string {
    if (!text) return '';
    return text
        // Remove bold/italic markers: **, *, __, _
        .replace(/\*\*([^*]+)\*\*/g, '$1')  // **bold**
        .replace(/\*([^*]+)\*/g, '$1')      // *italic*
        .replace(/__([^_]+)__/g, '$1')      // __bold__
        .replace(/_([^_]+)_/g, '$1')        // _italic_
        // Remove headers: ##, ###, ####
        .replace(/^#{1,6}\s*/gm, '')
        // Remove bullet points: - or *
        .replace(/^[\s]*[-*]\s+/gm, '• ')
        // Clean up extra whitespace
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

// ============================================================================
// Normalize artifact data for renderers
// Artifacts store data in content.data (generate) or content.core (knowledge_core)
// ============================================================================
function normalizeArtifact(type: TargetType, artifact: any): any {
    if (!artifact?.content) return null;
    const content = artifact.content;

    // Generate artifacts use content.data directly (e.g., { title, questions })
    // Knowledge cores use content.core
    // Try both paths for robustness

    switch (type) {
        case 'quiz':
            // content.data = { title, questions } for quiz
            return content.data || content.core?.quiz || content.quiz || null;
        case 'notes':
            // content.data = { title, sections } for notes
            return content.data || content.core?.notes || content.notes || null;
        case 'slides':
            // content.data = { title, slides, audience_level } for slides
            return content.data || content.core?.slides || content.slides || null;
        case 'flashcards':
            // content.data = { cards } for flashcards
            return content.data || content.core?.flashcards || content.flashcards || null;
        case 'exam':
            // content.data = FinalExamModel { title, questions, instructions, rubric }
            return content.data || content.core?.exam || content.exam || null;
        default:
            return null;
    }
}

// ============================================================================
// Status Cards
// ============================================================================
function StatusCard({ target, status, error, onClick, isActive }: {
    target: { type: TargetType; label: string; icon: string };
    status: string;
    error: string | null;
    onClick: () => void;
    isActive: boolean;
}) {
    const getStatusIcon = () => {
        switch (status) {
            case 'idle': return '⚪';
            case 'pending': return '🟡';
            case 'running': return '🔵';
            case 'completed': return '✅';
            case 'failed': return '❌';
            default: return '⚪';
        }
    };

    return (
        <div
            className={`status-card ${status} ${isActive ? 'active' : ''}`}
            onClick={onClick}
            title={error || ''}
        >
            <div className="status-icon">{getStatusIcon()}</div>
            <div className="status-label">{target.icon} {target.label}</div>
            {status === 'running' && <div className="status-spinner" />}
        </div>
    );
}

// ============================================================================
// Simple Renderers (will be enhanced)
// ============================================================================
function QuizRenderer({ data }: { data: any }) {
    const [answers, setAnswers] = useState<Record<string, number>>({});

    if (!data?.questions) return <div className="renderer-empty">No quiz data</div>;

    return (
        <div className="quiz-renderer">
            <h2>{data.title || 'Quiz'}</h2>
            {data.questions.map((q: any, idx: number) => {
                const answered = answers[q.id] !== undefined;
                const selected = answers[q.id];
                const correct = selected === q.correct_answer_index;

                return (
                    <div key={q.id || idx} className="quiz-question">
                        <div className="question-text">
                            <strong>{idx + 1}.</strong> {stripMarkdown(q.text)}
                        </div>
                        <div className="options-grid">
                            {q.options?.map((opt: string, i: number) => (
                                <button
                                    key={i}
                                    className={`option-btn ${answered ? (i === q.correct_answer_index ? 'correct' : i === selected ? 'wrong' : 'disabled') : ''}`}
                                    onClick={() => !answered && setAnswers(p => ({ ...p, [q.id || idx]: i }))}
                                    disabled={answered}
                                >
                                    {stripMarkdown(opt)}
                                </button>
                            ))}
                        </div>
                        {answered && (
                            <div className={`feedback ${correct ? 'success' : 'error'}`}>
                                {correct ? '✓ Correct!' : '✗ Incorrect.'} {stripMarkdown(q.explanation)}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

function NotesRenderer({ data }: { data: any }) {
    if (!data?.sections) return <div className="renderer-empty">No notes data</div>;

    return (
        <div className="notes-renderer">
            <h1>{data.title || 'Notes'}</h1>
            {data.sections.map((sec: any, i: number) => (
                <div key={i} className="notes-section">
                    <h2>{stripMarkdown(sec.heading)}</h2>
                    <p>{stripMarkdown(sec.content_block)}</p>
                    {sec.key_points && (
                        <ul className="key-points">
                            {sec.key_points.map((kp: string, k: number) => (
                                <li key={k}>{stripMarkdown(kp)}</li>
                            ))}
                        </ul>
                    )}
                </div>
            ))}
        </div>
    );
}

function SlidesRenderer({ data }: { data: any }) {
    if (!data?.slides) return <div className="renderer-empty">No slides data</div>;

    const downloadJSON = () => {
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'slides.json';
        a.click();
    };

    const downloadPPTX = async () => {
        // Dynamic import for client-side only
        const pptxgen = (await import('pptxgenjs')).default;
        const pres = new pptxgen();
        pres.layout = "LAYOUT_16x9";

        // Theme Colors
        const COLOR_PRIMARY = "1e1b4b";
        const COLOR_ACCENT = "6366f1";
        const COLOR_TEXT = "363636";
        const COLOR_BG_TITLE = "F1F5F9";

        // Title Slide
        let slide = pres.addSlide();
        slide.background = { color: COLOR_PRIMARY };
        slide.addText(stripMarkdown(data.title || 'Slides'), {
            x: 0.5, y: 2.5, w: '90%', fontSize: 44, align: 'center', color: 'FFFFFF', bold: true
        });
        slide.addText(`Audience: ${data.audience_level || 'General'}`, {
            x: 0.5, y: 4, w: '90%', fontSize: 20, align: 'center', color: 'CBD5E1'
        });
        slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: '100%', h: 0.5, fill: { color: COLOR_ACCENT } });

        // Content Slides
        data.slides.forEach((sItem: any) => {
            let s = pres.addSlide();

            // Header Bar
            s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: '100%', h: 1.2, fill: { color: COLOR_BG_TITLE } });
            s.addText(stripMarkdown(sItem.heading), {
                x: 0.5, y: 0.3, w: '90%', fontSize: 28, bold: true, color: COLOR_PRIMARY
            });

            // Main Idea Box
            s.addShape(pres.ShapeType.rect, {
                x: 0.5, y: 1.5, w: 9, h: 0.8,
                fill: { color: "EEF2FF" },
                line: { color: COLOR_ACCENT, width: 1 }
            });
            s.addText(stripMarkdown(sItem.main_idea), {
                x: 0.7, y: 1.6, w: 8.6, fontSize: 16, color: "4338CA", italic: true
            });

            // Bullets
            if (sItem.bullet_points) {
                const bullets = sItem.bullet_points.map((bp: string) => ({
                    text: stripMarkdown(bp),
                    options: { fontSize: 18, bullet: { type: 'number', color: COLOR_ACCENT } }
                }));
                s.addText(bullets, { x: 0.5, y: 2.6, w: '90%', h: 4, color: COLOR_TEXT });
            }

            // Speaker Notes
            if (sItem.speaker_notes) {
                s.addNotes(stripMarkdown(sItem.speaker_notes));
            }
        });

        pres.writeFile({ fileName: `${stripMarkdown(data.title || 'Slides')}.pptx` });
    };

    return (
        <div className="slides-renderer">
            <div className="slides-header">
                <h2>{data.title || 'Slides'}</h2>
                <div className="slides-actions">
                    <button onClick={downloadPPTX} className="download-btn primary">📊 Download PPTX</button>
                    <button onClick={downloadJSON} className="download-btn">📄 Download JSON</button>
                </div>
            </div>
            <div className="slides-grid">
                {data.slides.map((slide: any, i: number) => (
                    <div key={i} className="slide-card">
                        <h3>{stripMarkdown(slide.heading)}</h3>
                        <p className="main-idea">{stripMarkdown(slide.main_idea)}</p>
                        <ul>
                            {slide.bullet_points?.map((bp: string, b: number) => (
                                <li key={b}>{stripMarkdown(bp)}</li>
                            ))}
                        </ul>
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
        return <div className="renderer-empty">No flashcard data</div>;
    }

    const card = data.cards[index];
    const next = () => { setFlipped(false); setTimeout(() => setIndex(i => (i + 1) % data.cards.length), 200); };
    const prev = () => { setFlipped(false); setTimeout(() => setIndex(i => (i - 1 + data.cards.length) % data.cards.length), 200); };

    return (
        <div className="flashcard-renderer">
            <div className={`flashcard ${flipped ? 'flipped' : ''}`} onClick={() => setFlipped(!flipped)}>
                <div className="card-face front">
                    <p>{stripMarkdown(card.front)}</p>
                </div>
                <div className="card-face back">
                    <p>{stripMarkdown(card.back)}</p>
                    {card.hint && <small className="hint">💡 {stripMarkdown(card.hint)}</small>}
                </div>
            </div>
            <div className="card-controls">
                <button onClick={prev}>← Prev</button>
                <span>{index + 1} / {data.cards.length}</span>
                <button onClick={next}>Next →</button>
            </div>
        </div>
    );
}

function ExamRenderer({ data }: { data: any }) {
    const [showAnswers, setShowAnswers] = useState(false);

    if (!data?.questions || data.questions.length === 0) {
        return <div className="renderer-empty">No exam questions generated</div>;
    }

    return (
        <div className="exam-renderer">
            <div className="exam-header">
                <h2>{data.title || 'Final Exam'}</h2>
                <button
                    onClick={() => setShowAnswers(!showAnswers)}
                    className="download-btn"
                >
                    {showAnswers ? '🙈 Hide Answers' : '👁 Show Answers'}
                </button>
            </div>

            {data.instructions && (
                <div className="exam-instructions">
                    <strong>Instructions:</strong> {data.instructions}
                </div>
            )}

            <div className="exam-questions">
                {data.questions.map((q: any, idx: number) => (
                    <div key={q.id || idx} className="exam-question">
                        <div className="question-header">
                            <span className="question-number">{idx + 1}.</span>
                            <span className="question-type">{q.type}</span>
                            <span className="question-points">{q.points} pts</span>
                        </div>
                        <div className="question-text">{stripMarkdown(q.text)}</div>

                        {q.options && q.type === 'MCQ' && (
                            <div className="options-list">
                                {q.options.map((opt: string, i: number) => (
                                    <div key={i} className="option-item">
                                        {String.fromCharCode(65 + i)}. {stripMarkdown(opt)}
                                    </div>
                                ))}
                            </div>
                        )}

                        {showAnswers && (
                            <div className="answer-section">
                                <div className="model-answer">
                                    <strong>Model Answer:</strong> {stripMarkdown(q.model_answer || 'See grading notes')}
                                </div>
                                {q.grading_notes && (
                                    <div className="grading-notes">
                                        <strong>Grading:</strong> {stripMarkdown(q.grading_notes)}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {data.rubric && (
                <div className="exam-rubric">
                    <strong>Rubric:</strong> {data.rubric}
                </div>
            )}
        </div>
    );
}

// ============================================================================
// Main Workspace Page
// ============================================================================
export default function WorkspacePage() {
    const [sourceType, setSourceType] = useState<SourceType>('youtube');
    const [sourceValue, setSourceValue] = useState('');
    const [activeTab, setActiveTab] = useState<TargetType>('quiz');

    const { state, isRunning, runPipeline, reset } = useJobOrchestrator();

    const handleGenerate = () => {
        if (!sourceValue.trim()) return;
        const name = sourceValue.split('/').pop() || 'Untitled';
        runPipeline(sourceType, sourceValue, name);
    };

    const placeholder = SOURCE_TYPES.find(s => s.type === sourceType)?.placeholder || '';
    const activeArtifact = state.generate[activeTab].artifact;
    const normalizedData = activeArtifact ? normalizeArtifact(activeTab, activeArtifact) : null;

    return (
        <div className="workspace">
            {/* Header */}
            <header className="workspace-header">
                <h1>🐝 BeePrepared Workspace</h1>
                <p>Upload any source → Generate all study materials</p>
            </header>

            {/* Input Section */}
            <section className="input-section">
                <div className="source-types">
                    {SOURCE_TYPES.map(s => (
                        <button
                            key={s.type}
                            className={`source-btn ${sourceType === s.type ? 'active' : ''}`}
                            onClick={() => setSourceType(s.type)}
                            disabled={isRunning}
                        >
                            {s.label}
                        </button>
                    ))}
                </div>
                <div className="input-row">
                    <input
                        type="text"
                        value={sourceValue}
                        onChange={e => setSourceValue(e.target.value)}
                        placeholder={placeholder}
                        disabled={isRunning}
                        className="source-input"
                    />
                    <button
                        onClick={handleGenerate}
                        disabled={isRunning || !sourceValue.trim()}
                        className="generate-btn"
                    >
                        {isRunning ? '⏳ Processing...' : '🚀 Generate All'}
                    </button>
                    {isRunning && (
                        <button onClick={reset} className="reset-btn">✕ Cancel</button>
                    )}
                </div>

                {/* Ingest Status */}
                {state.ingest.status !== 'idle' && (
                    <div className={`ingest-status ${state.ingest.status}`}>
                        {state.ingest.status === 'pending' && '🟡 Queued for ingestion...'}
                        {state.ingest.status === 'running' && '🔵 Ingesting source...'}
                        {state.ingest.status === 'completed' && '✅ Source ingested'}
                        {state.ingest.status === 'failed' && `❌ Ingest failed: ${state.ingest.error}`}
                    </div>
                )}
            </section>

            {/* Status Grid */}
            <section className="status-grid">
                {TARGETS.map(t => (
                    <StatusCard
                        key={t.type}
                        target={t}
                        status={state.generate[t.type].status}
                        error={state.generate[t.type].error}
                        onClick={() => setActiveTab(t.type)}
                        isActive={activeTab === t.type}
                    />
                ))}
            </section>

            {/* Artifact Viewer */}
            <section className="artifact-viewer">
                <div className="viewer-tabs">
                    {TARGETS.map(t => (
                        <button
                            key={t.type}
                            className={`tab-btn ${activeTab === t.type ? 'active' : ''}`}
                            onClick={() => setActiveTab(t.type)}
                        >
                            {t.icon} {t.label}
                            {state.generate[t.type].status === 'completed' && ' ✓'}
                        </button>
                    ))}
                </div>

                <div className="viewer-content">
                    {state.generate[activeTab].status === 'idle' && (
                        <div className="viewer-placeholder">
                            <p>Select a source and click "Generate All" to see artifacts</p>
                        </div>
                    )}
                    {state.generate[activeTab].status === 'pending' && (
                        <div className="viewer-loading">🟡 Queued...</div>
                    )}
                    {state.generate[activeTab].status === 'running' && (
                        <div className="viewer-loading">🔵 Generating {activeTab}...</div>
                    )}
                    {state.generate[activeTab].status === 'failed' && (
                        <div className="viewer-error">❌ Failed: {state.generate[activeTab].error}</div>
                    )}
                    {state.generate[activeTab].status === 'completed' && (
                        <>
                            {activeTab === 'quiz' && <QuizRenderer data={normalizedData} />}
                            {activeTab === 'notes' && <NotesRenderer data={normalizedData} />}
                            {activeTab === 'slides' && <SlidesRenderer data={normalizedData} />}
                            {activeTab === 'flashcards' && <FlashcardRenderer data={normalizedData} />}
                            {activeTab === 'exam' && <ExamRenderer data={normalizedData} />}
                        </>
                    )}
                </div>
            </section>
        </div>
    );
}
