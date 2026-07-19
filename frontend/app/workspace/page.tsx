'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
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

function stripMarkdown(text: string | null | undefined): string {
    if (!text) return '';
    return text
        .replace(/!\[.*?\]\(.*?\)/g, '')           // images
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')   // links → just text
        .replace(/\*\*([^*]+)\*\*/g, '$1')         // **bold**
        .replace(/\*([^*]+)\*/g, '$1')             // *italic*
        .replace(/__([^_]+)__/g, '$1')             // __bold__
        .replace(/_([^_]+)_/g, '$1')               // _italic_
        .replace(/^#{1,6}\s*/gm, '')               // headers
        .replace(/`([^`]+)`/g, '$1')               // inline code
        .replace(/\n+/g, ' ')                      // newlines → space
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

function normalizeArtifact(type: TargetType, artifact: any): any {
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
        default:
            return null;
    }
}

const API_BASE = 'http://localhost:8000';

async function downloadBinary(artifactId: string, fallbackFilename: string): Promise<void> {
    try {
        console.log(`[Binary] Fetching download URL for artifact: ${artifactId}`);
        const res = await fetch(`${API_BASE}/api/artifacts/${artifactId}/download`);

        if (!res.ok) {
            const error = await res.json().catch(() => ({ detail: 'Unknown error' }));
            throw new Error(error.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        console.log(`[Binary] Got presigned URL with headers:`, {
            filename: data.filename,
            mime_type: data.mime_type,
            format: data.format,
        });

        const a = document.createElement('a');
        a.href = data.download_url;
        a.download = data.filename || fallbackFilename; // Forces download behavior
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);

        console.log(`[Binary] Download triggered: ${data.filename}`);
    } catch (error) {
        console.error('[Binary] Download failed:', error);
        alert(`Download failed: ${error instanceof Error ? error.message : 'Unknown error'}`);
    }
}

function getBinaryInfo(artifact: any): { format: string; available: boolean } | null {
    const binary = artifact?.content?.binary;
    if (!binary) return null;
    return {
        format: binary.format || 'bin',
        available: !!binary.storage_path,
    };
}

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
                            <strong>{idx + 1}.</strong> <MathTextInline>{q.text}</MathTextInline>
                        </div>
                        <div className="options-grid">
                            {q.options?.map((opt: string, i: number) => (
                                <button
                                    key={i}
                                    className={`option-btn ${answered ? (i === q.correct_answer_index ? 'correct' : i === selected ? 'wrong' : 'disabled') : ''}`}
                                    onClick={() => !answered && setAnswers(p => ({ ...p, [q.id || idx]: i }))}
                                    disabled={answered}
                                >
                                    <MathTextInline>{opt}</MathTextInline>
                                </button>
                            ))}
                        </div>
                        {answered && (
                            <div className={`feedback ${correct ? 'success' : 'error'}`}>
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
            <div className="notes-renderer markdown-notes">
                <h1>{data.title || 'Notes'}</h1>
                <div className="markdown-content">
                    <MathText>{data.body}</MathText>
                </div>
            </div>
        );
    }

    if (!data?.sections) return <div className="renderer-empty">No notes data</div>;

    return (
        <div className="notes-renderer">
            <h1>{data.title || 'Notes'}</h1>
            {data.sections.map((sec: any, i: number) => (
                <div key={i} className="notes-section">
                    <h2>{sec.heading}</h2>

                    {sec.key_points && sec.key_points.length > 0 && (
                        <ul className="key-points">
                            {sec.key_points.map((kp: string, k: number) => (
                                <li key={k}><MathTextInline>{kp}</MathTextInline></li>
                            ))}
                        </ul>
                    )}

                    {sec.content_block && (
                        <div className="content-block markdown-content">
                            <MathText>{sec.content_block}</MathText>
                        </div>
                    )}

                    {sec.key_terms && sec.key_terms.length > 0 && (
                        <div className="key-terms">
                            <strong>Key Terms:</strong>{' '}
                            {sec.key_terms.map((term: string, t: number) => (
                                <span key={t} className="term-badge">{term}</span>
                            ))}
                        </div>
                    )}

                    {sec.callouts && sec.callouts.length > 0 && (
                        <div className="callouts">
                            {sec.callouts.map((callout: string, c: number) => (
                                <div key={c} className="callout">⚠️ <MathTextInline>{callout}</MathTextInline></div>
                            ))}
                        </div>
                    )}
                </div>
            ))}
        </div>
    );
}

function SlidesRenderer({ data, artifact }: { data: any; artifact?: any }) {
    if (!data?.slides) return <div className="renderer-empty">No slides data</div>;

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
        <div className="slides-renderer">
            <div className="slides-header">
                <h2>{data.title || 'Slides'}</h2>
                <div className="slides-actions">
                    <button
                        onClick={handleDownloadPPTX}
                        className={`download-btn primary ${!binaryInfo?.available ? 'disabled' : ''}`}
                        disabled={!binaryInfo?.available}
                    >
                        📊 Download PPTX
                    </button>
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
                    <MathText>{card.front}</MathText>
                </div>
                <div className="card-face back">
                    <MathText>{card.back}</MathText>
                    {card.hint && <small className="hint">💡 <MathTextInline>{card.hint}</MathTextInline></small>}
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

function ExamRenderer({ data, artifact }: { data: any; artifact: any }) {
    const [showAnswers, setShowAnswers] = useState(false);
    const binaryInfo = getBinaryInfo(artifact);

    if (!data?.questions || data.questions.length === 0) {
        return <div className="renderer-empty">No exam questions generated</div>;
    }

    const handleDownloadPDF = () => {
        if (artifact?.id) {
            downloadBinary(artifact.id, 'final_exam.pdf');
        }
    };

    return (
        <div className="exam-renderer">
            <div className="exam-header">
                <h2>{data.title || 'Final Exam'}</h2>
                <div className="exam-actions">
                    {binaryInfo?.available && (
                        <button onClick={handleDownloadPDF} className="download-btn primary">
                            📄 Download PDF
                        </button>
                    )}
                    <button
                        onClick={() => setShowAnswers(!showAnswers)}
                        className="download-btn"
                    >
                        {showAnswers ? '🙈 Hide Answers' : '👁 Show Answers'}
                    </button>
                </div>
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
            <header className="workspace-header">
                <h1>🐝 BeePrepared Workspace</h1>
                <p>Upload any source → Generate all study materials</p>
            </header>

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

                {state.ingest.status !== 'idle' && (
                    <div className={`ingest-status ${state.ingest.status}`}>
                        {state.ingest.status === 'pending' && '🟡 Queued for ingestion...'}
                        {state.ingest.status === 'running' && '🔵 Ingesting source...'}
                        {state.ingest.status === 'completed' && '✅ Source ingested'}
                        {state.ingest.status === 'failed' && `❌ Ingest failed: ${state.ingest.error}`}
                    </div>
                )}
            </section>

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
                            {activeTab === 'slides' && <SlidesRenderer data={normalizedData} artifact={activeArtifact} />}
                            {activeTab === 'flashcards' && <FlashcardRenderer data={normalizedData} />}
                            {activeTab === 'exam' && <ExamRenderer data={normalizedData} artifact={activeArtifact} />}
                        </>
                    )}
                </div>
            </section>
        </div>
    );
}
