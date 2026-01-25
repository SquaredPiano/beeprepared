"use client";

import React, { useState } from "react";
import { 
  ChevronLeft, 
  ChevronRight, 
  CheckCircle2, 
  Circle, 
  Play, 
  RotateCcw,
  Book,
  Clock,
  Award,
  Plus,
  Search
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import Link from "next/link";

interface Question {
  id: string;
  text: string;
  options: string[];
  correctAnswer: number;
}

const mockQuestions: Question[] = [
  { 
    id: "1", 
    text: "Which neural network architecture introduced the concept of self-attention?", 
    options: ["RNN", "LSTM", "Transformer", "CNN"], 
    correctAnswer: 2 
  },
  { 
    id: "2", 
    text: "What does the 'GPT' in ChatGPT stand for?", 
    options: ["General Pre-trained Transformer", "Generative Pre-trained Transformer", "Global Processing Tool", "Generative Processing Technology"], 
    correctAnswer: 1 
  },
  { 
    id: "3", 
    text: "In machine learning, what is the 'Vanishing Gradient Problem' primarily associated with?", 
    options: ["Overfitting", "Data augmentation", "Deep neural networks with many layers", "Large batch sizes"], 
    correctAnswer: 2 
  },
];

export default function QuizzesPage() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [isAnswered, setIsAnswered] = useState(false);
  const [score, setScore] = useState(0);
  const [quizStarted, setQuizStarted] = useState(false);
  const [quizFinished, setQuizFinished] = useState(false);

  const startQuiz = () => {
    setQuizStarted(true);
    playSound("complete");
  };

  const handleOptionSelect = (index: number) => {
    if (isAnswered) return;
    setSelectedOption(index);
    playSound("pickup");
  };

  const submitAnswer = () => {
    if (selectedOption === null) return;
    setIsAnswered(true);
    if (selectedOption === mockQuestions[currentIndex].correctAnswer) {
      setScore(score + 1);
      playSound("complete");
    } else {
      playSound("drop");
    }
  };

  const nextQuestion = () => {
    if (currentIndex + 1 < mockQuestions.length) {
      setCurrentIndex(currentIndex + 1);
      setSelectedOption(null);
      setIsAnswered(false);
      playSound("pickup");
    } else {
      setQuizFinished(true);
      playSound("complete");
    }
  };

  const restartQuiz = () => {
    setCurrentIndex(0);
    setSelectedOption(null);
    setIsAnswered(false);
    setScore(0);
    setQuizFinished(false);
    playSound("pickup");
  };

  if (!quizStarted) {
    return (
      <div className="p-12 space-y-12 max-w-7xl mx-auto min-h-screen flex flex-col items-center justify-center text-center">
        <div className="space-y-6">
          <div className="w-24 h-24 rounded-full bg-honey-100 flex items-center justify-center text-honey-600 mx-auto">
            <Book size={48} />
          </div>
          <div className="space-y-4">
            <h1 className="text-6xl font-display font-bold uppercase tracking-tighter">Evaluation <br /><span className="italic lowercase opacity-40">Protocol</span></h1>
            <p className="text-xs font-bold uppercase tracking-[0.3em] opacity-40 max-w-md mx-auto leading-relaxed">
              Test your architectural understanding of the processed artifacts.
            </p>
          </div>
          <div className="flex gap-8 justify-center pt-8">
            <div className="text-center">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-40">Questions</p>
              <p className="text-2xl font-display font-bold">{mockQuestions.length}</p>
            </div>
            <div className="w-px h-12 bg-border/20" />
            <div className="text-center">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-40">Est. Time</p>
              <p className="text-2xl font-display font-bold">5 Min</p>
            </div>
          </div>
          <button 
            onClick={startQuiz}
            className="mt-12 px-12 py-6 bg-bee-black text-white text-xs font-black uppercase tracking-[0.4em] rounded-[2rem] hover:bg-honey-600 transition-all shadow-2xl hover:scale-105 active:scale-95 flex items-center gap-4"
          >
            Initiate Assessment
            <Play size={16} fill="currentColor" />
          </button>
        </div>
      </div>
    );
  }

  if (quizFinished) {
    return (
      <div className="p-12 space-y-12 max-w-7xl mx-auto min-h-screen flex flex-col items-center justify-center text-center">
        <motion.div 
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className="space-y-8"
        >
          <div className="w-32 h-32 rounded-full bg-honey-500 flex items-center justify-center text-white mx-auto shadow-2xl shadow-honey-500/40">
            <Award size={64} />
          </div>
          <div className="space-y-4">
            <h2 className="text-5xl font-display font-bold uppercase tracking-tighter">Synthesis Complete</h2>
            <p className="text-xs font-bold uppercase tracking-[0.3em] opacity-40">Assessment Score</p>
            <div className="text-8xl font-display font-bold text-honey-600">
              {Math.round((score / mockQuestions.length) * 100)}%
            </div>
          </div>
          <div className="pt-12 flex gap-4 justify-center">
            <button 
              onClick={restartQuiz}
              className="px-10 py-5 border-2 border-bee-black text-bee-black text-[10px] font-black uppercase tracking-[0.3em] rounded-2xl hover:bg-bee-black hover:text-white transition-all"
            >
              Restart
            </button>
            <Link 
              href="/dashboard/library"
              className="px-10 py-5 bg-bee-black text-white text-[10px] font-black uppercase tracking-[0.3em] rounded-2xl hover:bg-honey-600 transition-all shadow-xl"
            >
              Finish Session
            </Link>
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="p-12 space-y-12 max-w-5xl mx-auto min-h-screen">
      <header className="flex items-center justify-between">
        <Link 
          href="/dashboard/library"
          className="text-[10px] font-bold uppercase tracking-[0.2em] opacity-40 hover:opacity-100 transition-opacity flex items-center gap-2"
        >
          <ChevronLeft size={14} />
          Exit Quiz
        </Link>
        <div className="flex items-center gap-6">
          <div className="text-right">
            <p className="text-[10px] font-bold uppercase tracking-widest opacity-40">Progress</p>
            <p className="text-xs font-bold uppercase tracking-widest">
              Question {currentIndex + 1} <span className="opacity-20">/</span> {mockQuestions.length}
            </p>
          </div>
          <div className="w-32 h-2 bg-stone-100 rounded-full overflow-hidden">
            <motion.div 
              className="h-full bg-honey-500"
              initial={{ width: 0 }}
              animate={{ width: `${((currentIndex + 1) / mockQuestions.length) * 100}%` }}
            />
          </div>
        </div>
      </header>

      <main className="space-y-12 pt-12">
        <motion.div
          key={currentIndex}
          initial={{ x: 20, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -20, opacity: 0 }}
          className="space-y-12"
        >
          <h2 className="text-4xl font-display font-bold uppercase tracking-tight leading-tight max-w-3xl">
            {mockQuestions[currentIndex].text}
          </h2>

          <div className="grid grid-cols-1 gap-4">
            {mockQuestions[currentIndex].options.map((option, i) => (
              <button
                key={i}
                onClick={() => handleOptionSelect(i)}
                className={cn(
                  "p-8 rounded-[2rem] border-2 text-left transition-all duration-300 flex items-center justify-between group",
                  selectedOption === i 
                    ? "border-bee-black bg-bee-black text-white shadow-xl translate-x-2" 
                    : "border-border/20 hover:border-honey-400 hover:bg-honey-50/10",
                  isAnswered && i === mockQuestions[currentIndex].correctAnswer && "border-green-500 bg-green-50 text-green-700",
                  isAnswered && selectedOption === i && i !== mockQuestions[currentIndex].correctAnswer && "border-red-500 bg-red-50 text-red-700"
                )}
              >
                <div className="flex items-center gap-6">
                  <div className={cn(
                    "w-10 h-10 rounded-xl flex items-center justify-center text-[10px] font-black border-2 transition-colors",
                    selectedOption === i ? "border-white/20 bg-white/10" : "border-border/20 bg-muted group-hover:border-honey-200"
                  )}>
                    {String.fromCharCode(65 + i)}
                  </div>
                  <span className="text-sm font-bold uppercase tracking-widest">{option}</span>
                </div>
                {isAnswered && i === mockQuestions[currentIndex].correctAnswer && <CheckCircle2 className="text-green-500" />}
                {!isAnswered && selectedOption === i && <div className="w-2 h-2 rounded-full bg-white animate-pulse" />}
              </button>
            ))}
          </div>
        </motion.div>

        <div className="pt-8 border-t border-border/10 flex justify-between items-center">
          <div className="flex items-center gap-4 opacity-40">
            <Clock size={14} />
            <span className="text-[10px] font-bold uppercase tracking-widest">Time elapsed: 02:45</span>
          </div>
          
          <button
            disabled={selectedOption === null}
            onClick={isAnswered ? nextQuestion : submitAnswer}
            className={cn(
              "px-12 py-6 rounded-[2rem] text-xs font-black uppercase tracking-[0.3em] transition-all shadow-2xl flex items-center gap-4",
              selectedOption === null 
                ? "bg-muted text-muted-foreground cursor-not-allowed opacity-50" 
                : "bg-bee-black text-white hover:bg-honey-600 hover:scale-105"
            )}
          >
            {isAnswered ? (currentIndex + 1 === mockQuestions.length ? "View Final Synthesis" : "Next Protocol") : "Verify Selection"}
            <ChevronRight size={16} />
          </button>
        </div>
      </main>
    </div>
  );
}
