"use client";

import React, { useState } from "react";
import { 
  ChevronLeft, 
  FileText, 
  Download, 
  Eye, 
  Search, 
  Filter,
  MoreVertical,
  ArrowUpRight,
  ShieldCheck,
  Calendar,
  Layers,
  Trash2,
  Share2
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import Link from "next/link";

interface Exam {
  id: string;
  title: string;
  type: string;
  date: string;
  size: string;
  questions: number;
  difficulty: "Baseline" | "Intermediate" | "Expert";
}

const mockExams: Exam[] = [
  { id: "1", title: "Microeconomics_Final_Synthesis_2026.pdf", type: "PDF", date: "Jan 24, 2026", size: "2.4 MB", questions: 45, difficulty: "Expert" },
  { id: "2", title: "ML_Foundations_Assessment_Draft.pdf", type: "PDF", date: "Jan 23, 2026", size: "1.8 MB", questions: 30, difficulty: "Baseline" },
  { id: "3", title: "Architectural_History_Exam_Matrix.pdf", type: "PDF", date: "Jan 22, 2026", size: "3.1 MB", questions: 50, difficulty: "Intermediate" },
];

export default function MockExamsPage() {
  const [exams, setExams] = useState<Exam[]>(mockExams);

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
            Mock <br /> 
            <span className="italic lowercase opacity-40">Exams</span>
          </h1>
        </div>

        <div className="flex gap-4">
          <div className="glass px-6 py-3 rounded-2xl border border-border/40 flex items-center gap-4">
            <Search size={16} className="opacity-20" />
            <input 
              placeholder="Filter assessments..." 
              className="bg-transparent border-none focus:outline-none text-[10px] font-bold uppercase tracking-widest w-48"
            />
          </div>
          <button className="bg-bee-black text-white px-8 py-4 rounded-2xl hover:bg-honey-500 transition-all flex items-center gap-3 text-xs font-bold uppercase tracking-widest shadow-xl">
            <ShieldCheck size={16} />
            Verify New Exam
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6">
        {exams.map((exam, i) => (
          <motion.div
            key={exam.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            className="group glass p-10 rounded-[3rem] border border-border/40 hover:border-honey-500/50 transition-all flex items-center justify-between relative overflow-hidden"
          >
            {/* Background Accent */}
            <div className="absolute top-0 right-0 p-12 opacity-0 group-hover:opacity-5 transition-opacity">
              <FileText size={180} className="-rotate-12" />
            </div>

            <div className="flex items-center gap-10 relative z-10">
              <div className="w-20 h-20 bg-muted rounded-3xl flex items-center justify-center text-bee-black/20 group-hover:bg-honey-500 group-hover:text-white transition-all duration-500 shadow-2xl group-hover:shadow-honey-500/40">
                <FileText size={32} />
              </div>
              
              <div className="space-y-3">
                <div className="flex items-center gap-4">
                  <span className={cn(
                    "px-3 py-1 rounded-full text-[8px] font-black uppercase tracking-widest",
                    exam.difficulty === "Expert" ? "bg-red-50 text-red-600" : 
                    exam.difficulty === "Intermediate" ? "bg-honey-50 text-honey-700" : 
                    "bg-green-50 text-green-600"
                  )}>
                    {exam.difficulty} Rank
                  </span>
                  <div className="flex items-center gap-2 text-[10px] font-bold opacity-30 uppercase tracking-widest">
                    <Calendar size={12} />
                    {exam.date}
                  </div>
                </div>
                <h3 className="text-2xl font-display font-bold uppercase tracking-tight group-hover:text-honey-600 transition-colors">{exam.title}</h3>
                <div className="flex items-center gap-6 text-[10px] font-bold uppercase tracking-widest opacity-40">
                  <span className="flex items-center gap-2"><Layers size={12} /> {exam.questions} Questions</span>
                  <div className="w-1 h-1 rounded-full bg-border" />
                  <span>{exam.size}</span>
                  <div className="w-1 h-1 rounded-full bg-border" />
                  <span className="text-honey-600">Awaiting Simulation</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-4 relative z-10">
              <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-all translate-x-4 group-hover:translate-x-0">
                <button className="p-4 glass rounded-2xl hover:bg-honey-50 transition-colors shadow-lg"><Share2 size={18} /></button>
                <button className="p-4 glass rounded-2xl hover:bg-honey-50 transition-colors shadow-lg"><Download size={18} /></button>
                <button className="p-4 glass rounded-2xl hover:bg-red-50 hover:text-red-600 transition-colors shadow-lg"><Trash2 size={18} /></button>
              </div>
              <button 
                onClick={() => playSound("complete")}
                className="bg-bee-black text-white px-10 py-5 rounded-[2rem] text-[10px] font-black uppercase tracking-[0.3em] hover:bg-honey-600 transition-all shadow-2xl flex items-center gap-3 active:scale-95"
              >
                Launch Exam
                <ArrowUpRight size={16} />
              </button>
            </div>
          </motion.div>
        ))}
      </div>

      {/* Pro Tip Section */}
      <div className="p-12 glass rounded-[4rem] border-2 border-honey-500/20 bg-honey-50/5 flex items-center gap-12">
        <div className="w-24 h-24 rounded-full bg-honey-500 flex items-center justify-center text-white shrink-0">
          <ShieldCheck size={48} />
        </div>
        <div className="space-y-3">
          <h3 className="text-2xl font-display font-bold uppercase tracking-tight">Verified Protocol</h3>
          <p className="text-sm font-medium opacity-60 leading-relaxed max-w-2xl">
            Our Mock Exams are architected using the same cognitive weights as your processed materials. Each exam includes detailed rationales and hierarchical feedback to ensure complete synthesis of the subject matter.
          </p>
        </div>
      </div>
    </div>
  );
}
