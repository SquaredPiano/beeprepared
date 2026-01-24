"use client";

import React, { useState } from "react";
import { HoneyDropZone } from "@/components/HoneyDropZone";
import { useStore } from "@/store/useStore";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowLeft, 
  Play, 
  Sparkles,
  Info
} from "lucide-react";
import Link from "next/link";

export default function UploadPage() {
  const { files, isProcessing, setProcessing } = useStore();
  const [showProgress, setShowProgress] = useState(false);

  const startProcessing = () => {
    setProcessing(true);
    setShowProgress(true);
  };

  const totalProgress = files.length > 0 
    ? files.reduce((acc, f) => acc + f.progress, 0) / files.length 
    : 0;

  return (
    <div className="max-w-7xl mx-auto px-6 py-12 space-y-16">
      <header className="flex items-center justify-between">
        <Link 
          href="/dashboard" 
          className="group flex items-center gap-3 text-[10px] font-bold uppercase tracking-[0.2em] opacity-40 hover:opacity-100 transition-opacity cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Dashboard
        </Link>
        <div className="flex items-center gap-2 px-4 py-2 rounded-full border border-border/40 text-[10px] font-bold uppercase tracking-widest opacity-60">
          <Info className="w-3 h-3 text-honey-500" />
          Available Capacity: 85%
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-24 items-start">
        <div className="space-y-12">
          <div className="space-y-6">
            <motion.h1 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="text-6xl font-display uppercase tracking-tighter leading-[0.9]"
            >
              Add New <br />
              <span className="font-serif italic lowercase opacity-40">Content</span>
            </motion.h1>
            <p className="text-muted-foreground leading-relaxed max-w-md">
              Upload your documents to begin analysis. We'll extract key insights and organize them into your study flow.
            </p>
          </div>

          <HoneyDropZone />

          {files.length > 0 && !isProcessing && (
            <motion.button
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              onClick={startProcessing}
              className="w-full group flex items-center justify-center gap-6 bg-bee-black text-white py-6 rounded-2xl hover:bg-honey-500 transition-all duration-500 shadow-2xl cursor-pointer"
            >
              <span className="font-display text-lg uppercase tracking-widest font-bold text-center">Start Analysis</span>
              <div className="w-12 h-12 bg-white/10 rounded-full flex items-center justify-center group-hover:scale-110 transition-transform">
                <Play className="w-6 h-6 text-white fill-current" />
              </div>
            </motion.button>
          )}
        </div>

        <div className="sticky top-32 space-y-12">
          <AnimatePresence mode="wait">
            {showProgress ? (
              <motion.div
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                className="space-y-12"
              >
                <div className="space-y-4 text-center">
                  <h2 className="font-display text-xs uppercase tracking-[0.3em] font-bold opacity-40">Current Flow</h2>
                  <div className="p-12 glass rounded-[3rem] border border-border/40">
                    <div className="relative w-48 h-48 mx-auto flex items-center justify-center">
                      <svg className="w-full h-full -rotate-90">
                        <circle
                          cx="96"
                          cy="96"
                          r="88"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="8"
                          className="text-muted/20"
                        />
                        <motion.circle
                          cx="96"
                          cy="96"
                          r="88"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="8"
                          strokeDasharray="553"
                          initial={{ strokeDashoffset: 553 }}
                          animate={{ strokeDashoffset: 553 - (553 * (totalProgress || 45)) / 100 }}
                          className="text-honey-500"
                        />
                      </svg>
                      <div className="absolute inset-0 flex flex-col items-center justify-center">
                        <span className="text-4xl font-display font-bold">{Math.round(totalProgress || 45)}%</span>
                        <span className="text-[10px] uppercase tracking-widest font-bold opacity-40">Complete</span>
                      </div>
                    </div>
                  </div>
                </div>
              </motion.div>
            ) : (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="py-32 border-2 border-dashed border-border/40 rounded-[3rem] flex flex-col items-center justify-center text-center px-12 space-y-6"
              >
                <div className="w-20 h-20 bg-muted rounded-full flex items-center justify-center">
                  <Sparkles className="w-8 h-8 opacity-20" />
                </div>
                <div className="space-y-2">
                  <h3 className="font-display text-lg uppercase tracking-widest opacity-40">Ready to Flow</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed italic">
                    Add files to visualize your learning path.
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
