"use client";

import React, { useState, useEffect } from "react";
import { 
  ChevronLeft, 
  ChevronRight, 
  RotateCcw, 
  Plus, 
  Search,
  MoreVertical,
  Layout,
  ExternalLink,
  Trash2,
  Edit3
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import Link from "next/link";

interface Flashcard {
  id: string;
  front: string;
  back: string;
  category: string;
}

const mockFlashcards: Flashcard[] = [
  { id: "1", front: "What is the primary function of a Convolutional Neural Network (CNN)?", back: "Processing data with a grid-like topology, such as images, by using convolutional layers to extract hierarchical features.", category: "AI & ML" },
  { id: "2", front: "Define 'Backpropagation' in the context of neural networks.", back: "An algorithm used to calculate the gradient of the loss function with respect to the weights of the network, enabling efficient training via gradient descent.", category: "AI & ML" },
  { id: "3", front: "What are the three main components of a Transformer architecture?", back: "Self-attention mechanism, Feed-forward neural networks, and Positional encoding.", category: "NLP" },
];

export default function FlashcardsPage() {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isFlipped, setIsFlipped] = useState(false);
  const [cards, setCards] = useState<Flashcard[]>(mockFlashcards);

  const nextCard = () => {
    setIsFlipped(false);
    setTimeout(() => {
      setCurrentIndex((prev) => (prev + 1) % cards.length);
      playSound("pickup");
    }, 150);
  };

  const prevCard = () => {
    setIsFlipped(false);
    setTimeout(() => {
      setCurrentIndex((prev) => (prev - 1 + cards.length) % cards.length);
      playSound("pickup");
    }, 150);
  };

  const flipCard = () => {
    setIsFlipped(!isFlipped);
    playSound("drop");
  };

  return (
    <div className="p-12 space-y-12 max-w-7xl mx-auto min-h-screen">
      <header className="flex items-end justify-between">
        <div className="space-y-4">
          <Link 
            href="/dashboard/library"
            className="text-[10px] font-bold uppercase tracking-[0.2em] opacity-40 hover:opacity-100 transition-opacity flex items-center gap-2"
          >
            <ChevronLeft size={14} />
            Back to Library
          </Link>
          <h1 className="text-6xl font-display uppercase tracking-tighter leading-[0.8]">
            Flashcard <br /> 
            <span className="italic lowercase opacity-40">Matrix</span>
          </h1>
        </div>

        <div className="flex gap-4">
          <div className="glass px-6 py-3 rounded-2xl border border-border/40 flex items-center gap-4">
            <Search size={16} className="opacity-20" />
            <input 
              placeholder="Search concepts..." 
              className="bg-transparent border-none focus:outline-none text-[10px] font-bold uppercase tracking-widest w-48"
            />
          </div>
          <button className="bg-bee-black text-white px-8 py-4 rounded-2xl hover:bg-honey-500 transition-all flex items-center gap-3 text-xs font-bold uppercase tracking-widest shadow-xl">
            <Plus size={16} />
            New Card
          </button>
        </div>
      </header>

      <div className="grid grid-cols-12 gap-12">
        {/* Main Training Area */}
        <div className="col-span-8 space-y-12">
          <div className="relative perspective-1000 h-[500px] w-full">
            <motion.div
              animate={{ rotateY: isFlipped ? 180 : 0 }}
              transition={{ duration: 0.6, type: "spring", stiffness: 260, damping: 20 }}
              className="w-full h-full relative preserve-3d cursor-pointer"
              onClick={flipCard}
            >
              {/* Front */}
              <div className={cn(
                "absolute inset-0 backface-hidden glass rounded-[4rem] border-2 border-border/20 p-20 flex flex-col items-center justify-center text-center space-y-8 bg-white",
                isFlipped && "pointer-events-none"
              )}>
                <div className="absolute top-12 left-12 px-4 py-1 bg-honey-50 text-honey-700 rounded-full text-[8px] font-bold uppercase tracking-[0.2em]">
                  {cards[currentIndex].category}
                </div>
                <div className="w-20 h-20 rounded-3xl bg-honey-100 flex items-center justify-center text-honey-600 mb-4">
                  <Layout size={32} />
                </div>
                <h2 className="text-3xl font-display font-bold uppercase tracking-tight leading-tight max-w-xl">
                  {cards[currentIndex].front}
                </h2>
                <p className="text-[10px] font-bold uppercase tracking-[0.3em] opacity-20">Click to reveal architecture</p>
              </div>

              {/* Back */}
              <div className={cn(
                "absolute inset-0 backface-hidden glass rounded-[4rem] border-2 border-honey-500/40 p-20 flex flex-col items-center justify-center text-center space-y-8 bg-honey-50/5 rotate-y-180",
                !isFlipped && "pointer-events-none"
              )}>
                <div className="absolute top-12 left-12 px-4 py-1 bg-honey-500 text-white rounded-full text-[8px] font-bold uppercase tracking-[0.2em]">
                  Verified Synthesis
                </div>
                <p className="text-2xl font-medium leading-relaxed max-w-xl text-bee-black/80">
                  {cards[currentIndex].back}
                </p>
                <div className="flex gap-4 pt-8">
                  <button className="px-6 py-2 rounded-xl bg-red-50 text-red-600 text-[8px] font-black uppercase tracking-widest hover:bg-red-100 transition-colors">Needs Review</button>
                  <button className="px-6 py-2 rounded-xl bg-green-50 text-green-600 text-[8px] font-black uppercase tracking-widest hover:bg-green-100 transition-colors">Mastered</button>
                </div>
              </div>
            </motion.div>
          </div>

          <div className="flex items-center justify-between px-12">
            <div className="flex gap-4">
              <button 
                onClick={prevCard}
                className="w-16 h-16 rounded-full border border-border/40 flex items-center justify-center hover:bg-honey-50 transition-all active:scale-95"
              >
                <ChevronLeft size={24} />
              </button>
              <button 
                onClick={nextCard}
                className="w-16 h-16 rounded-full bg-bee-black text-white flex items-center justify-center hover:bg-honey-500 transition-all active:scale-95 shadow-xl"
              >
                <ChevronRight size={24} />
              </button>
            </div>

            <div className="flex items-center gap-8">
              <div className="text-right">
                <p className="text-[10px] font-bold uppercase tracking-widest opacity-40">Progress</p>
                <p className="text-lg font-display font-bold uppercase tracking-tighter">
                  {currentIndex + 1} <span className="opacity-20">/</span> {cards.length}
                </p>
              </div>
              <div className="w-px h-10 bg-border/20" />
              <button 
                onClick={() => { setCurrentIndex(0); setIsFlipped(false); playSound("complete"); }}
                className="flex items-center gap-3 text-[10px] font-bold uppercase tracking-[0.3em] opacity-40 hover:opacity-100 transition-opacity"
              >
                <RotateCcw size={14} />
                Restart Session
              </button>
            </div>
          </div>
        </div>

        {/* Sidebar Deck Info */}
        <div className="col-span-4 space-y-8">
          <div className="glass rounded-[3rem] border border-border/40 p-10 space-y-8">
            <h3 className="text-xs font-bold uppercase tracking-[0.3em] opacity-40">Active Deck</h3>
            
            <div className="space-y-4">
              {cards.map((card, i) => (
                <div 
                  key={card.id}
                  onClick={() => { setCurrentIndex(i); setIsFlipped(false); }}
                  className={cn(
                    "p-6 rounded-3xl border transition-all cursor-pointer group",
                    currentIndex === i 
                      ? "bg-honey-500 border-honey-400 text-white shadow-lg shadow-honey-500/20" 
                      : "bg-stone-50/50 border-border/10 hover:border-honey-300"
                  )}
                >
                  <div className="flex items-start justify-between gap-4">
                    <p className={cn(
                      "text-[10px] font-medium line-clamp-2 uppercase tracking-tight",
                      currentIndex === i ? "text-white" : "opacity-60"
                    )}>
                      {card.front}
                    </p>
                    <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button className="p-1 hover:bg-white/20 rounded"><Edit3 size={12} /></button>
                      <button className="p-1 hover:bg-white/20 rounded"><Trash2 size={12} /></button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <div className="pt-4 border-t border-border/10 space-y-6">
              <div className="flex justify-between items-center">
                <span className="text-[10px] font-bold uppercase tracking-widest opacity-40">Session Stats</span>
                <span className="text-[10px] font-black uppercase text-honey-600">84% Retention</span>
              </div>
              <div className="h-2 bg-stone-100 rounded-full overflow-hidden">
                <div className="h-full bg-honey-500 w-[84%]" />
              </div>
            </div>
          </div>

          <div className="p-10 glass-card rounded-[3rem] bg-honey-500 text-white space-y-6 shadow-2xl shadow-honey-500/40 overflow-hidden relative group">
            <div className="relative z-10 space-y-4">
              <h3 className="text-xl font-display font-bold uppercase tracking-tight">Export Deck</h3>
              <p className="text-[10px] font-medium opacity-80 uppercase tracking-widest leading-relaxed">
                Download this deck as Anki or PDF format for offline training.
              </p>
              <button className="w-full py-4 bg-white text-bee-black rounded-2xl text-[10px] font-black uppercase tracking-[0.2em] hover:bg-stone-100 transition-all flex items-center justify-center gap-3">
                Download Artifacts
                <ExternalLink size={14} />
              </button>
            </div>
            <Layout size={120} className="absolute -bottom-10 -right-10 opacity-10 group-hover:scale-110 transition-transform duration-700" />
          </div>
        </div>
      </div>
    </div>
  );
}
