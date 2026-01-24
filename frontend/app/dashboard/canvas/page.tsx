"use client";

import { PipelineCanvas } from "@/components/canvas/PipelineCanvas";
import { AgentPalette } from "@/components/canvas/AgentPalette";
import { ArrowLeft, Plus } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";

export default function CanvasPage() {
  return (
    <div className="flex flex-col h-screen bg-stone-50/30 overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-8 py-6 border-b border-border/40 bg-white/50 backdrop-blur-md h-24 shrink-0">
        <div className="flex items-center gap-8">
          <Link 
            href="/dashboard" 
            className="group flex items-center gap-3 text-[10px] font-bold uppercase tracking-[0.2em] opacity-40 hover:opacity-100 transition-opacity cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
            Exit View
          </Link>
          <div className="h-4 w-px bg-border/60" />
            <div className="space-y-0.5">
              <h1 className="text-sm font-bold uppercase tracking-widest">Content Flow</h1>
              <p className="text-[10px] opacity-40 uppercase tracking-tighter">Interactive Visualization</p>
            </div>
          </div>
  
          <div className="flex items-center gap-4">
            <Link 
              href="/upload" 
              className="group flex items-center gap-3 bg-bee-black text-white px-6 py-2.5 rounded-full hover:bg-honey-500 transition-all cursor-pointer"
            >
              <span className="text-[10px] font-bold uppercase tracking-widest">Add Content</span>
              <Plus className="w-4 h-4" />
            </Link>
        </div>
      </header>

      {/* Canvas Area */}
      <main className="flex-1 p-8 relative">
        <AgentPalette />
        <motion.div 
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          className="w-full h-full"
        >
          <PipelineCanvas />
        </motion.div>
      </main>
    </div>
  );
}
