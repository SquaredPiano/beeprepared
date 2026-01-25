"use client";

import React, { useState, useRef } from "react";
import { 
  X, 
  Upload, 
  File, 
  CheckCircle2, 
  Loader2, 
  AlertCircle,
  FileText,
  Video,
  Music,
  Plus
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import { useIngestionStore } from "@/store/ingestionStore";
import { useMascotAI } from "@/hooks/useMascotAI";

interface UploadModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function UploadModal({ isOpen, onClose }: UploadModalProps) {
  const [dragActive, setDragActive] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { addFile } = useIngestionStore();
  const { triggerReaction } = useMascotAI();

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFiles(Array.from(e.dataTransfer.files));
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      handleFiles(Array.from(e.target.files));
    }
  };

  const handleFiles = (newFiles: File[]) => {
    setFiles((prev) => [...prev, ...newFiles]);
    playSound("pickup");
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
    playSound("drop");
  };

  const handleUpload = async () => {
    if (files.length === 0) return;
    
    setUploading(true);
    playSound("complete");
    
    // Simulate upload progress
    for (let i = 0; i <= 100; i += 10) {
      setProgress(i);
      await new Promise(r => setTimeout(r, 100));
    }

    // Add to ingestion store
    files.forEach(file => {
      // Logic to add to ingestion store and eventually create a node
      // For now we'll just simulate it
      console.log("Uploading file:", file.name);
    });

    // Mascot reaction to upload complete
    if (files.length > 0) {
      triggerReaction({
        event: 'upload_complete',
        data: {
          filename: files[0].name,
          count: files.length,
          type: files[0].type
        }
      });
    }

    setUploading(false);
    setFiles([]);
    setProgress(0);
    onClose();
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-6">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-bee-black/60 backdrop-blur-sm"
          />
          
          <motion.div
            initial={{ scale: 0.9, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.9, opacity: 0, y: 20 }}
            className="relative w-full max-w-2xl glass-card rounded-[3rem] border-2 border-border/40 bg-white overflow-hidden shadow-2xl"
          >
            {/* Header */}
            <div className="px-10 py-8 border-b border-border/10 flex items-center justify-between bg-stone-50/50">
              <div className="space-y-1">
                <h2 className="text-2xl font-display font-bold uppercase tracking-tight">Ingest Artifacts</h2>
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] opacity-40">Support for PDF, MP4, MP3, PPTX</p>
              </div>
              <button 
                onClick={onClose}
                className="p-3 hover:bg-honey-100 rounded-2xl transition-colors opacity-40 hover:opacity-100"
              >
                <X size={20} />
              </button>
            </div>

            {/* Content */}
            <div className="p-10 space-y-8">
              {!uploading ? (
                <>
                  <div
                    onDragEnter={handleDrag}
                    onDragLeave={handleDrag}
                    onDragOver={handleDrag}
                    onDrop={handleDrop}
                    onClick={() => inputRef.current?.click()}
                    className={cn(
                      "relative border-2 border-dashed rounded-[2.5rem] p-12 transition-all duration-500 cursor-pointer group overflow-hidden",
                      dragActive ? "border-honey-500 bg-honey-50/50 scale-[0.99]" : "border-border/20 hover:border-honey-400 hover:bg-honey-50/10"
                    )}
                  >
                    <input
                      ref={inputRef}
                      type="file"
                      multiple
                      onChange={handleChange}
                      className="hidden"
                    />
                    
                    <div className="flex flex-col items-center gap-6 text-center relative z-10">
                      <div className="w-20 h-20 rounded-[1.5rem] bg-honey-100 flex items-center justify-center text-honey-600 group-hover:scale-110 transition-transform duration-500">
                        <Upload size={32} />
                      </div>
                      <div className="space-y-2">
                        <h3 className="text-lg font-bold uppercase tracking-widest">Drop files here</h3>
                        <p className="text-xs opacity-40 font-medium max-w-[240px] leading-relaxed">
                          Drag and drop your educational materials to start the extraction process
                        </p>
                      </div>
                      <div className="px-6 py-2 bg-bee-black text-white text-[10px] font-bold uppercase tracking-widest rounded-full group-hover:bg-honey-600 transition-colors">
                        Select from Hive
                      </div>
                    </div>

                    {/* Decorative Elements */}
                    <div className="absolute -bottom-10 -right-10 opacity-5 group-hover:opacity-10 transition-opacity">
                      <Plus size={160} />
                    </div>
                  </div>

                  {files.length > 0 && (
                    <div className="space-y-4 max-h-[240px] overflow-y-auto pr-4 scrollbar-hide">
                      <AnimatePresence>
                        {files.map((file, index) => (
                          <motion.div
                            key={`${file.name}-${index}`}
                            initial={{ x: -20, opacity: 0 }}
                            animate={{ x: 0, opacity: 1 }}
                            exit={{ x: 20, opacity: 0 }}
                            className="flex items-center justify-between p-5 glass border border-border/10 rounded-3xl group"
                          >
                            <div className="flex items-center gap-4">
                              <div className="w-10 h-10 rounded-xl bg-honey-100 flex items-center justify-center text-honey-600">
                                {file.type.includes("video") ? <Video size={18} /> : 
                                 file.type.includes("audio") ? <Music size={18} /> : 
                                 <FileText size={18} />}
                              </div>
                              <div className="text-left">
                                <p className="text-xs font-bold uppercase tracking-widest truncate max-w-[200px]">{file.name}</p>
                                <p className="text-[10px] opacity-40 font-medium">{(file.size / (1024 * 1024)).toFixed(2)} MB</p>
                              </div>
                            </div>
                            <button 
                              onClick={(e) => { e.stopPropagation(); removeFile(index); }}
                              className="p-2 hover:bg-red-50 text-red-500 rounded-lg opacity-0 group-hover:opacity-100 transition-all"
                            >
                              <X size={14} />
                            </button>
                          </motion.div>
                        ))}
                      </AnimatePresence>
                    </div>
                  )}

                  <button
                    disabled={files.length === 0}
                    onClick={handleUpload}
                    className={cn(
                      "w-full py-6 rounded-[2rem] text-xs font-bold uppercase tracking-[0.3em] transition-all flex items-center justify-center gap-4 shadow-xl",
                      files.length > 0 
                        ? "bg-bee-black text-white hover:bg-honey-600 hover:scale-[1.02] active:scale-[0.98]" 
                        : "bg-muted text-muted-foreground cursor-not-allowed opacity-50"
                    )}
                  >
                    Deploy to Pipeline
                    <CheckCircle2 size={16} />
                  </button>
                </>
              ) : (
                <div className="py-12 flex flex-col items-center gap-8 text-center">
                  <div className="relative">
                    <div className="w-32 h-32 rounded-full border-4 border-honey-100 flex items-center justify-center">
                      <Loader2 size={48} className="text-honey-500 animate-spin" />
                    </div>
                    <div className="absolute inset-0 flex items-center justify-center">
                      <span className="text-sm font-bold font-display">{progress}%</span>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-xl font-bold uppercase tracking-widest">Architecting Knowledge</h3>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-honey-600 animate-pulse">
                      Analyzing {files.length} artifact(s) structure...
                    </p>
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
