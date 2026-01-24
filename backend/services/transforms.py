from backend.models.artifacts import QuizModel, FlashcardModel, Flashcard, QuizQuestion

def quiz_to_flashcards(quiz: QuizModel) -> FlashcardModel:
    """
    Deterministically transforms a Quiz into Flashcards.
    Front: Question Text
    Back: Correct Answer + Explanation
    """
    cards = []
    for q in quiz.questions:
        # For MCQ, maybe list options on Front? Or just the question?
        # Usually flashcards are recall, so just question is better.
        front_text = q.text
        
        # Resolve correct answer from index
        if 0 <= q.correct_answer_index < len(q.options):
            correct_txt = q.options[q.correct_answer_index]
        else:
            correct_txt = "Answer Key Missing"
            
        back_text = f"**{correct_txt}**\n\n{q.explanation}"
        
        cards.append(Flashcard(
            id=f"fc-from-{q.id}",
            front=front_text,
            back=back_text,
            hint="Recall the quiz question.",
            source_reference=f"Quiz Q{q.id}"
        ))
    
    return FlashcardModel(
        title=f"Flashcards from {quiz.title}",
        cards=cards
    )

def flashcards_to_quiz(flashcards: FlashcardModel) -> QuizModel:
    """
    Transforms Flashcards into a basic Quiz (Self-Check style).
    """
    questions = []
    for i, card in enumerate(flashcards.cards):
        # Create a single-option question (Self Check)
        # or mock options? Strict schema requires correct_answer_index.
        # We'll put the correct answer at index 0.
        questions.append(QuizQuestion(
            id=f"q-from-{i}",
            text=f"Recite the definition/answer for: {card.front}",
            type="MCQ", # Pseudo-MCQ
            options=[card.back, "I don't know"], # 2 options
            correct_answer_index=0, # Index of card.back
            explanation=f"Hint: {card.hint or 'No hint'}",
            topic_focus="Recall"
        ))
        
    return QuizModel(
        title=f"Quiz from {flashcards.title}",
        questions=questions
    )
