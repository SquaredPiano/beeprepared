"use client";

import React, { useState } from "react";
import { 
  ChevronLeft, 
  Presentation, 
  Download, 
  Play, 
  Search, 
  Filter,
  MoreVertical,
  Layout,
  Layers,
  Monitor,
  Share2,
  Trash2,
  ExternalLink,
  Plus
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import Link from "next/link";

interface Deck {
  id: string;
  title: string;
  slides: number;
  date: string;
  size: string;
  theme: string;
}

const mockDecks: Deck[] = [
  { id: "1", title: "Microeconomics_Market_Dynamics_Synthesis.pptx", slides: 24, date: "Jan 24, 2026", size: "12.4 MB", theme: "Architectural" },
  { id: "2", title: "Deep_Learning_Neural_Hierarchies.pptx", slides: 18, date: "Jan 23, 2026", size: "8.2 MB", theme: "Minimalist" },
  { id: "3", title: "Global_Supply_Chain_Architecture.pptx", slides: 32, date: "Jan 22, 2026", size: "15.1 MB", theme: "Corporate" },
];

export default function PPTXPage() {
  const [decks, setDecks] = useState<Deck[]>(mockDecks);

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
            Artifact <br /> 
            <span className="italic lowercase opacity-40">Presentations</span>
          </h1>
        </div>

        <div className="flex gap-4">
          <div className="glass px-6 py-3 rounded-2xl border border-border/40 flex items-center gap-4">
            <Search size={16} className="opacity-20" />
            <input 
              placeholder="Search decks..." 
              className="bg-transparent border-none focus:outline-none text-[10px] font-bold uppercase tracking-widest w-48"
            />
          </div>
          <button className="bg-bee-black text-white px-8 py-4 rounded-2xl hover:bg-honey-500 transition-all flex items-center gap-3 text-xs font-bold uppercase tracking-widest shadow-xl">
            <Plus size={16} />
            New Presentation
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        {decks.map((deck, i) => (
          <motion.div
            key={deck.id}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.1 }}
            className="group glass rounded-[3rem] border border-border/40 hover:border-honey-500/50 transition-all overflow-hidden flex flex-col"
          >
            {/* Slide Preview */}
            <div className="aspect-video bg-muted relative overflow-hidden flex items-center justify-center p-12">
              <div className="absolute inset-0 bg-gradient-to-br from-honey-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <Presentation size={64} className="text-bee-black/10 group-hover:scale-110 group-hover:text-honey-500/40 transition-all duration-700" />
              
              <div className="absolute bottom-6 left-6 right-6 flex justify-between items-end">
                <div className="px-3 py-1 bg-white/80 backdrop-blur-md rounded-full text-[8px] font-black uppercase tracking-widest">
                  {deck.theme} Theme
                </div>
                <div className="flex gap-2 translate-y-12 group-hover:translate-y-0 transition-transform duration-500">
                  <button className="w-10 h-10 rounded-full bg-white shadow-xl flex items-center justify-center hover:bg-honey-50 transition-colors"><Share2 size={14} /></button>
                  <button className="w-10 h-10 rounded-full bg-white shadow-xl flex items-center justify-center hover:bg-honey-50 transition-colors"><Download size={14} /></button>
                </div>
              </div>
            </div>

            {/* Deck Info */}
            <div className="p-8 space-y-6 flex-1 flex flex-col justify-between">
              <div className="space-y-3">
                <h3 className="text-xl font-display font-bold uppercase tracking-tight line-clamp-2 leading-tight group-hover:text-honey-600 transition-colors">
                  {deck.title}
                </h3>
                <div className="flex items-center gap-4 text-[10px] font-bold uppercase tracking-widest opacity-40">
                  <span className="flex items-center gap-2"><Layout size={12} /> {deck.slides} Slides</span>
                  <div className="w-1 h-1 rounded-full bg-border" />
                  <span>{deck.size}</span>
                </div>
              </div>

              <div className="pt-6 border-t border-border/10 flex items-center justify-between">
                <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">{deck.date}</span>
                <button 
                  onClick={() => playSound("pickup")}
                  className="flex items-center gap-3 text-[10px] font-black uppercase tracking-[0.2em] text-honey-600 hover:text-honey-700 transition-colors group/btn"
                >
                  Launch Player
                  <Play size={12} className="fill-current group-hover/btn:scale-125 transition-transform" />
                </button>
              </div>
            </div>
          </motion.div>
        ))}

        {/* Upload Placeholder */}
        <button
          className="group rounded-[3rem] border-2 border-dashed border-border/40 hover:border-honey-500 transition-all flex flex-col items-center justify-center gap-6 min-h-[400px] bg-honey-50/5 hover:bg-honey-50/20"
        >
          <div className="w-16 h-16 rounded-full bg-white shadow-xl flex items-center justify-center group-hover:scale-110 transition-transform">
            <Monitor className="w-8 h-8 text-honey-600" />
          </div>
          <div className="text-center space-y-2">
            <h3 className="text-sm font-bold uppercase tracking-widest text-bee-black">Synthesize Presentation</h3>
            <p className="text-[10px] font-medium opacity-40 uppercase tracking-tighter">Transform any artifact into slides</p>
          </div>
        </button>
      </div>
    </div>
  );
}
