import { useState, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import pptxgen from "pptxgenjs";
import 'katex/dist/katex.min.css';
import Latex from 'react-katex';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import './App.css'

function App() {
  const [activeTab, setActiveTab] = useState('quiz')
  const [quizData, setQuizData] = useState(null)
  const [flashcards, setFlashcards] = useState(null)
  const [notes, setNotes] = useState(null)
  const [slides, setSlides] = useState(null)

  // Quiz State: { [questionId]: selectedOptionIndex }
  const [quizAnswers, setQuizAnswers] = useState({})

  useEffect(() => {
    fetch('/data/quiz.json').then(res => res.json()).then(setQuizData).catch(console.error)
    fetch('/data/flashcards.json').then(res => res.json()).then(setFlashcards).catch(console.error)
    fetch('/data/notes.json').then(res => res.json()).then(setNotes).catch(console.error)
    fetch('/data/slides.json').then(res => res.json()).then(setSlides).catch(console.error)
  }, [])

  const handleQuizSelect = (qId, optionIdx) => {
    if (quizAnswers[qId] !== undefined) return; // Prevent changing after selection
    setQuizAnswers(prev => ({ ...prev, [qId]: optionIdx }))
  }

  const handleExportPPTX = () => {
    if (!slides) return;
    let pres = new pptxgen();
    pres.layout = "LAYOUT_16x9";

    // Theme Colors
    const COLOR_PRIMARY = "1e1b4b"; // Dark Blue
    const COLOR_ACCENT = "6366f1"; // Indigo
    const COLOR_TEXT = "363636";
    const COLOR_BG_TITLE = "F1F5F9";

    // Title Slide
    let slide = pres.addSlide();
    slide.background = { color: COLOR_PRIMARY };
    slide.addText(slides.title, { x: 0.5, y: 2.5, w: '90%', fontSize: 44, align: 'center', color: 'FFFFFF', bold: true });
    slide.addText(`Audience: ${slides.audience_level}`, { x: 0.5, y: 4, w: '90%', fontSize: 20, align: 'center', color: 'CBD5E1' });

    // Decorative Element (Facet Theme style)
    slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: '100%', h: 0.5, fill: COLOR_ACCENT });

    // Content Slides
    slides.slides.forEach(sItem => {
      let s = pres.addSlide();

      // Header Bar
      s.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: '100%', h: 1.2, fill: COLOR_BG_TITLE });
      s.addText(sItem.heading, { x: 0.5, y: 0.3, w: '90%', fontSize: 28, bold: true, color: COLOR_PRIMARY });

      // Main Idea Box
      s.addShape(pres.ShapeType.rect, { x: 0.5, y: 1.5, w: 9, h: 0.8, fill: "EEF2FF", line: { color: COLOR_ACCENT, width: 1 } });
      s.addText(sItem.main_idea, { x: 0.7, y: 1.6, w: 8.6, fontSize: 16, color: "4338CA", italic: true });

      // Bullets
      if (sItem.bullet_points) {
        let bullets = sItem.bullet_points.map(bp => ({
          text: bp,
          options: { fontSize: 18, indentLevel: 0, bullet: { type: 'number', color: COLOR_ACCENT } }
        }));
        s.addText(bullets, { x: 0.5, y: 2.6, w: '90%', h: 4, color: COLOR_TEXT });
      }

      s.addNotes(sItem.speaker_notes);
    });

    pres.writeFile({ fileName: "Lecture_Slides.pptx" });
  }

  return (
    <div className="app-container">
      <header>
        <h1>BeePrepared Artifacts</h1>
        <p style={{ color: '#94a3b8' }}>Interactive Learning Content Generator</p>
      </header>

      <div className="nav-tabs">
        {['quiz', 'flashcards', 'notes', 'slides'].map(tab => (
          <button
            key={tab}
            className={`nav-btn ${activeTab === tab ? 'active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <main className="artifact-view">
        {/* --- QUIZ VIEW --- */}
        {activeTab === 'quiz' && quizData && (
          <div className="quiz-view">
            <h2>{quizData.title}</h2>
            {quizData.questions.map((q, idx) => {
              const isAnswered = quizAnswers[q.id] !== undefined;
              const selectedIdx = quizAnswers[q.id];
              const isCorrect = selectedIdx === q.correct_answer_index;

              return (
                <div key={q.id} className="quiz-item">
                  <div className="question-text">
                    <span style={{ color: '#818cf8', fontWeight: 'bold' }}>{idx + 1}.</span> <Latex>{q.text}</Latex>
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
                          <Latex>{opt}</Latex>
                        </div>
                      )
                    })}
                  </div>
                  {isAnswered && (
                    <div className={`feedback-box ${isCorrect ? 'success' : 'info'}`}>
                      <strong>{isCorrect ? "Correct!" : "Incorrect."}</strong>
                      <div style={{ marginTop: '0.5rem' }}><Latex>{q.explanation}</Latex></div>
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
            <h1>{notes.title}</h1>
            {notes.sections.map((sec, i) => (
              <div key={i} style={{ marginBottom: '2rem' }}>
                <h2 style={{ color: '#818cf8' }}>{sec.heading}</h2>
                <ReactMarkdown
                  remarkPlugins={[remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                >
                  {sec.content_block}
                </ReactMarkdown>
                {sec.key_points && (
                  <ul className='key-points-list'>
                    {sec.key_points.map((kp, k) => (
                      <li key={k} style={{ color: '#cbd5e1' }}>
                        <Latex>{kp}</Latex>
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2>{slides.title} Preview</h2>
              <button onClick={handleExportPPTX} className="download-btn">
                Download .PPTX (Facet Theme)
              </button>
            </div>
            <div className="slide-grid">
              {slides.slides.map((s, i) => (
                <div key={i} className="slide-card">
                  <h3 style={{ color: '#e2e8f0' }}>{i + 1}. {s.heading}</h3>
                  <div style={{ fontSize: '0.9rem', color: '#818cf8', marginBottom: '1rem', fontStyle: 'italic' }}>
                    {s.main_idea}
                  </div>
                  <ul style={{ paddingLeft: '1.2rem' }}>
                    {s.bullet_points.map((bp, b) => <li key={b} style={{ color: '#94a3b8' }}>{bp}</li>)}
                  </ul>
                  <div style={{ borderTop: '1px solid rgba(255,255,255,0.1)', marginTop: '1rem', paddingTop: '0.5rem', fontSize: '0.85rem', color: '#64748b' }}>
                    <strong>Speaker Notes:</strong> {s.speaker_notes.substring(0, 100)}...
                  </div>
                </div>
              ))}
            </div>
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
        e.preventDefault(); // prevent scroll
        setFlipped(f => !f);
      }
      if (e.code === 'ArrowRight') {
        nextCard();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [index]); // Dependency ensures nextCard uses correct index closure if needed.

  const card = cards[index]

  return (
    <div className="flashcard-container">
      <div className={`flashcard ${flipped ? 'flipped' : ''}`} onClick={() => setFlipped(!flipped)}>
        <div className="card-face card-front">
          <h3><Latex>{card.front}</Latex></h3>
          {card.source_reference && <span style={{ position: 'absolute', bottom: '1rem', fontSize: '0.8rem', opacity: 0.6 }}>{card.source_reference}</span>}
        </div>
        <div className="card-face card-back">
          <div style={{ fontSize: '1.2rem' }}><Latex>{card.back}</Latex></div>
          {card.hint && <div style={{ marginTop: '1rem', color: '#f1f5f9', opacity: 0.8 }}>💡 <Latex>{card.hint}</Latex></div>}
        </div>
      </div>
      <div className="card-controls">
        <button className="control-btn" onClick={() => setFlipped(!flipped)}>
          Flip (Space)
        </button>
        <button className="control-btn" onClick={nextCard} style={{ background: '#818cf8', color: 'white' }}>
          Next Card (→)
        </button>
      </div>
      <p style={{ marginTop: '2rem', color: '#64748b' }}>{index + 1} / {cards.length}</p>
    </div>
  )
}

export default App
