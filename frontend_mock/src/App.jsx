import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import pptxgen from "pptxgenjs";
import 'katex/dist/katex.min.css';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import './App.css'

// Helper to render mixed text and LaTeX safely
const RenderText = ({ text }) => {
  if (!text) return null;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        p: ({ node, ...props }) => <span {...props} />
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

function App() {
  const [activeTab, setActiveTab] = useState('quiz')
  const [quizData, setQuizData] = useState(null)
  const [flashcards, setFlashcards] = useState(null)
  const [notes, setNotes] = useState(null)
  const [slides, setSlides] = useState(null)
  const [examUrl, setExamUrl] = useState(null)

  // Quiz State
  const [quizAnswers, setQuizAnswers] = useState({})

  useEffect(() => {
    fetch('/data/quiz.json').then(res => res.json()).then(setQuizData).catch(console.error)
    fetch('/data/flashcards.json').then(res => res.json()).then(setFlashcards).catch(console.error)
    fetch('/data/notes.json').then(res => res.json()).then(setNotes).catch(console.error)
    fetch('/data/slides.json').then(res => res.json()).then(setSlides).catch(console.error)
    // Check if exam exists
    fetch('/data/final_exam.pdf').then(res => {
      if (res.ok) setExamUrl('/data/final_exam.pdf')
    }).catch(console.error)
  }, [])

  // --- TRANSFORMS ---
  const convertQuizToFlashcards = () => {
    if (!quizData) return;
    const newCards = quizData.questions.map(q => ({
      front: q.text,
      back: q.options && q.correct_answer_index !== undefined ? q.options[q.correct_answer_index] : "Answer Check Notes",
      hint: "From Quiz Recalled",
      source_reference: "Quiz Conversion"
    }));
    setFlashcards({ cards: newCards });
    setActiveTab('flashcards');
  }

  const convertNotesToSlides = () => {
    if (!notes) return;
    const newSlides = notes.sections.map(sec => ({
      heading: sec.heading,
      main_idea: sec.key_points ? sec.key_points[0] : "Key Concept",
      bullet_points: sec.key_points || ["See notes for details"],
      speaker_notes: sec.content_block ? sec.content_block.substring(0, 200) : ""
    }));
    setSlides({
      title: notes.title,
      audience_level: "Converted from Notes",
      slides: newSlides
    });
    setActiveTab('slides');
  }

  const handleQuizSelect = (qId, optionIdx) => {
    if (quizAnswers[qId] !== undefined) return;
    setQuizAnswers(prev => ({ ...prev, [qId]: optionIdx }))
  }

  const handleExportPPTX = () => {
    if (!slides) return;
    let pres = new pptxgen();
    pres.layout = "LAYOUT_16x9";

    const COLOR_PRIMARY = "1e1b4b";
    const COLOR_ACCENT = "6366f1";
    const COLOR_TEXT = "363636";
    const COLOR_BG_TITLE = "F1F5F9";

    let slide = pres.addSlide();
    slide.background = { color: COLOR_PRIMARY };
    // Title Slide: Perfectly centered
    slide.addText(slides.title, { x: 0, y: '30%', w: '100%', h: 1.5, fontSize: 44, align: 'center', valign: 'middle', color: 'FFFFFF', bold: true });
    slide.addText(`Audience: ${slides.audience_level}`, { x: 0, y: '50%', w: '100%', h: 0.5, fontSize: 20, align: 'center', valign: 'top', color: 'CBD5E1' });

    // Bottom Accent Bar
    slide.addShape(pres.ShapeType.rect, { x: 0, y: 5.4, w: '100%', h: 0.225, fill: COLOR_ACCENT });

    slides.slides.forEach(sItem => {
      let s = pres.addSlide();

      // Header Bar (Clean, Top)
      s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: '100%', h: 1.0, fill: COLOR_BG_TITLE });
      s.addText(sItem.heading, { x: 0.5, y: 0.1, w: 9, h: 0.8, fontSize: 32, bold: true, color: COLOR_PRIMARY, align: 'center', valign: 'middle' });

      // Accent Line
      s.addShape(pres.ShapeType.line, { x: 1, y: 1.2, w: 8, h: 0, line: { color: COLOR_ACCENT, width: 2 } });

      // Main Idea (Centered, Italic)
      s.addText(sItem.main_idea, { x: 1.5, y: 1.5, w: 7, h: 1, fontSize: 20, color: "4338CA", italic: true, align: 'center', valign: 'middle' });

      // Bullets (Centered Block, Left Aligned Text)
      // We place the text box in the center (x=1.5, w=7), but align text left for readability
      if (sItem.bullet_points) {
        let bullets = sItem.bullet_points.map(bp => ({
          text: bp,
          options: { fontSize: 20, indentLevel: 0, bullet: { type: 'number', color: COLOR_ACCENT }, breakLine: true }
        }));
        // Use a narrower text box to force centering of the content visually
        s.addText(bullets, { x: 2.0, y: 2.8, w: 6.0, h: 2.5, color: COLOR_TEXT, align: 'left', valign: 'top', lineSpacing: 32 });
      }
      s.addNotes(sItem.speaker_notes);
    });
    pres.writeFile({ fileName: "Lecture_Slides_Professional.pptx" });
  }

  return (
    <div className="app-container">
      <header>
        <h1>BeePrepared Learning Hub</h1>
        <p style={{ color: '#94a3b8' }}>Unified Content Generation System</p>
      </header>

      <div className="nav-tabs">
        {['quiz', 'flashcards', 'notes', 'slides', 'exam'].map(tab => (
          <button
            key={tab}
            className={`nav-btn ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab === 'exam' ? 'Final Exam' : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <main className="artifact-view">
        {/* --- QUIZ VIEW --- */}
        {activeTab === 'quiz' && quizData && (
          <div className="quiz-view">
            <div className="view-header">
              <h2>{quizData.title}</h2>
              <button className="action-btn" onClick={convertQuizToFlashcards}>Practice as Flashcards →</button>
            </div>
            {quizData.questions.map((q, idx) => {
              const isAnswered = quizAnswers[q.id] !== undefined;
              const selectedIdx = quizAnswers[q.id];
              const isCorrect = selectedIdx === q.correct_answer_index;
              return (
                <div key={q.id} className="quiz-item">
                  <div className="question-text">
                    <span style={{ color: '#818cf8', fontWeight: 'bold', marginRight: '0.5rem' }}>{idx + 1}.</span>
                    <RenderText text={q.text} />
                  </div>
                  <div className="options-grid">
                    {q.options.map((opt, i) => {
                      let btnClass = "option-btn";
                      if (isAnswered) {
                        if (i === q.correct_answer_index) btnClass += " correct";
                        else if (i === selectedIdx) btnClass += " wrong";
                        else btnClass += " disabled";
                      }
                      return (
                        <div key={i} className={btnClass} onClick={() => handleQuizSelect(q.id, i)}>
                          <RenderText text={opt} />
                        </div>
                      )
                    })}
                  </div>
                  {isAnswered && (
                    <div className={`feedback-box ${isCorrect ? 'success' : 'info'}`}>
                      <strong>{isCorrect ? "Correct!" : "Incorrect."}</strong>
                      <div style={{ marginTop: '0.5rem' }}><RenderText text={q.explanation} /></div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {/* --- FLASHCARDS VIEW --- */}
        {activeTab === 'flashcards' && flashcards && (
          <FlashcardDeck cards={flashcards.cards} />
        )}

        {/* --- NOTES VIEW --- */}
        {activeTab === 'notes' && notes && (
          <div className="notes-view markdown-body">
            <div className="view-header">
              <h1>{notes.title}</h1>
              <button className="action-btn" onClick={convertNotesToSlides}>Generate Slides →</button>
            </div>
            {notes.sections.map((sec, i) => (
              <div key={i} style={{ marginBottom: '2rem' }}>
                <h2 style={{ color: '#818cf8' }}>{sec.heading}</h2>
                <RenderText text={sec.content_block} />
                {sec.key_points && (
                  <ul className='key-points-list'>
                    {sec.key_points.map((kp, k) => (
                      <li key={k} style={{ color: '#cbd5e1' }}>
                        <RenderText text={kp} />
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}

        {/* --- SLIDES VIEW --- */}
        {activeTab === 'slides' && slides && (
          <div className="slides-view">
            <div className="view-header">
              <h2>{slides.title} Preview</h2>
              <button onClick={handleExportPPTX} className="download-btn">Download .PPTX</button>
            </div>
            <div className="slide-grid">
              {slides.slides.map((s, i) => (
                <div key={i} className="slide-card">
                  <div className="slide-preview-content">
                    <h3 style={{ color: '#1e1b4b', marginBottom: '0.5rem' }}>{s.heading}</h3>
                    <div style={{ fontSize: '0.9rem', color: '#4338CA', marginBottom: '1rem', fontStyle: 'italic', borderLeft: '2px solid #6366f1', paddingLeft: '0.5rem' }}>
                      {s.main_idea}
                    </div>
                    <ul style={{ paddingLeft: '1.2rem', color: '#334155' }}>
                      {s.bullet_points.map((bp, b) => <li key={b}>{bp}</li>)}
                    </ul>
                  </div>
                  <div className="slide-notes-preview">
                    <strong>Speaker Notes:</strong> {s.speaker_notes.substring(0, 100)}...
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* --- EXAM VIEW --- */}
        {activeTab === 'exam' && (
          <div className="exam-view" style={{ height: '100%', minHeight: '80vh' }}>
            {examUrl ? (
              <>
                <div className="view-header">
                  <h2>Final Exam PDF</h2>
                  <a href={examUrl} download="Final_Exam.pdf" className="download-btn">Download Exam PDF</a>
                </div>
                <iframe src={examUrl} width="100%" height="800px" style={{ border: 'none', borderRadius: '8px' }} />
              </>
            ) : (
              <div style={{ padding: '2rem', textAlign: 'center' }}>
                <h2>No Exam PDF Generated</h2>
                <p>Check the backend generation logs.</p>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}

function FlashcardDeck({ cards }) {
  const [index, setIndex] = useState(0)
  const [flipped, setFlipped] = useState(false)

  const nextCard = () => {
    setFlipped(false)
    setTimeout(() => setIndex((i) => (i + 1) % cards.length), 300)
  }

  // Key press for spacebar
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.code === 'Space') {
        e.preventDefault();
        setFlipped(f => !f);
      }
      if (e.code === 'ArrowRight') nextCard();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [index]);

  if (!cards || cards.length === 0) return <div>No cards available.</div>;

  const card = cards[index] || cards[0];

  return (
    <div className="flashcard-container">
      <div className={`flashcard ${flipped ? 'flipped' : ''}`} onClick={() => setFlipped(!flipped)}>
        <div className="card-face card-front">
          <h3 style={{ fontSize: '1.5rem' }}><RenderText text={card.front} /></h3>
          {card.source_reference && <span style={{ position: 'absolute', bottom: '1rem', fontSize: '0.8rem', opacity: 0.6 }}>{card.source_reference}</span>}
        </div>
        <div className="card-face card-back">
          <div style={{ fontSize: '1.3rem' }}><RenderText text={card.back} /></div>
          {card.hint && <div style={{ marginTop: '1rem', color: '#f1f5f9', opacity: 0.8 }}>💡 <RenderText text={card.hint} /></div>}
        </div>
      </div>
      <div className="card-controls">
        <button className="control-btn" onClick={() => setFlipped(!flipped)}>Flip (Space)</button>
        <button className="control-btn" onClick={nextCard} style={{ background: '#818cf8', color: 'white' }}>Next Card (→)</button>
      </div>
      <p style={{ marginTop: '2rem', color: '#64748b' }}>{index + 1} / {cards.length}</p>
    </div>
  )
}

export default App
