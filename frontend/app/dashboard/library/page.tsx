"use client";

import React from "react";
import { Search, Filter, MoreVertical, FileText, Download, Trash2, Eye } from "lucide-react";
import { motion } from "framer-motion";

const artifacts = [
  { id: "1", name: "Lecture_Notes_Architectural_History.pdf", type: "PDF", size: "2.4 MB", date: "Jan 22, 2026", status: "completed" },
  { id: "2", name: "Deep_Learning_Synthesis.mp3", type: "Audio", size: "15.8 MB", date: "Jan 21, 2026", status: "completed" },
  { id: "3", name: "Organic_Chemistry_Matrix.pdf", type: "PDF", size: "1.1 MB", date: "Jan 20, 2026", status: "processing" },
];

export default function LibraryPage() {
  return (
    <div className="p-12 space-y-12">
      <header className="space-y-4">
        <h1 className="text-5xl font-display uppercase tracking-tighter">Knowledge <br /> <span className="italic lowercase opacity-40">Library</span></h1>
        <p className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-40 max-w-xs leading-relaxed">
          Your archived artifacts and synthesized knowledge base.
        </p>
      </header>

      <div className="flex flex-col md:flex-row gap-6 justify-between items-end border-b border-border/40 pb-8">
        <div className="flex items-center gap-4 glass px-6 py-3 rounded-2xl border border-border/40 w-full md:w-96">
          <Search className="w-4 h-4 opacity-40" />
          <input 
            type="text" 
            placeholder="Search artifacts..." 
            className="bg-transparent border-none focus:outline-none text-xs uppercase tracking-widest font-bold w-full"
          />
        </div>
        <div className="flex gap-4">
          <button className="glass px-6 py-3 rounded-2xl border border-border/40 flex items-center gap-3 text-[10px] font-bold uppercase tracking-widest hover:bg-honey-50 transition-all cursor-pointer">
            <Filter className="w-4 h-4 opacity-40" />
            Filter
          </button>
          <button className="bg-bee-black text-white px-8 py-3 rounded-2xl text-[10px] font-bold uppercase tracking-widest hover:bg-honey-500 transition-all cursor-pointer">
            Export All
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4">
        {artifacts.map((artifact, i) => (
          <motion.div
            key={artifact.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="group flex items-center justify-between p-6 glass rounded-3xl border border-border/40 hover:border-honey-300 transition-all cursor-pointer"
          >
            <div className="flex items-center gap-8">
              <div className="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center group-hover:bg-honey-100 group-hover:text-honey-600 transition-colors">
                <FileText className="w-6 h-6" />
              </div>
              <div>
                <h3 className="text-lg font-display font-bold uppercase tracking-tight">{artifact.name}</h3>
                <div className="flex items-center gap-4 mt-1 opacity-40 text-[10px] font-bold uppercase tracking-[0.2em]">
                  <span>{artifact.type}</span>
                  <div className="w-1 h-1 rounded-full bg-border" />
                  <span>{artifact.size}</span>
                  <div className="w-1 h-1 rounded-full bg-border" />
                  <span>{artifact.date}</span>
                </div>
              </div>
            </div>
            
            <div className="flex items-center gap-4">
              <div className="flex opacity-0 group-hover:opacity-100 transition-opacity gap-2">
                <button className="p-3 hover:bg-muted rounded-xl transition-colors"><Eye className="w-4 h-4" /></button>
                <button className="p-3 hover:bg-muted rounded-xl transition-colors"><Download className="w-4 h-4" /></button>
                <button className="p-3 hover:bg-red-50 hover:text-red-600 rounded-xl transition-colors"><Trash2 className="w-4 h-4" /></button>
              </div>
              <button className="p-3 opacity-20 group-hover:opacity-100 transition-opacity"><MoreVertical className="w-5 h-5" /></button>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
