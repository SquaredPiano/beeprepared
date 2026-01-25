"use client";

import React, { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ArrowLeft, 
  Upload, 
  FileText, 
  CheckCircle2, 
  Loader2, 
  ShieldCheck,
  Zap,
  Hexagon,
  ChevronRight
} from "lucide-react";
import Link from "next/link";
import { api, Job } from "@/lib/api";
import { ProjectSelector } from "@/components/upload/ProjectSelector";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface UploadingFile {
  id: string;
  file: File;
  status: "pending" | "uploading" | "processing" | "completed" | "error";
  progress: number;
  jobId?: string;
  error?: string;
}

export default function UploadPage() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [uploadQueue, setUploadQueue] = useState<UploadingFile[]>([]);
  const [isProcessing, setIsProcessing] = useState(false);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    const newFiles = acceptedFiles.map(file => ({
      id: Math.random().toString(36).substring(7),
      file,
      status: "pending" as const,
      progress: 0
    }));
    setUploadQueue(prev => [...prev, ...newFiles]);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "audio/*": [".mp3", ".wav", ".m4a"],
      "video/*": [".mp4", ".mov", ".avi"],
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
      "text/markdown": [".md"],
      "text/plain": [".txt"]
    }
  });

  const startIngestion = async () => {
    if (!selectedProjectId) {
      toast.error("Please select a target project first");
      return;
    }

    setIsProcessing(true);
    
    // Process files one by one (or in parallel)
    const filesToProcess = uploadQueue.filter(f => f.status === "pending");
    
    for (const item of filesToProcess) {
      setUploadQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: "uploading" } : f));
      
      try {
        await api.upload.uploadAndIngest(
          selectedProjectId,
          item.file,
          (job: Job) => {
            setUploadQueue(prev => prev.map(f => f.id === item.id ? { 
              ...f, 
              status: job.status === "running" ? "processing" : "uploading",
              jobId: job.id
            } : f));
          }
        );
        
        setUploadQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: "completed" } : f));
        toast.success(`Synthesized ${item.file.name}`);
      } catch (err: any) {
        console.error("Upload failed:", err);
        setUploadQueue(prev => prev.map(f => f.id === item.id ? { ...f, status: "error", error: err.message } : f));
        toast.error(`Fault detected in ${item.file.name}`);
      }
    }
    
    setIsProcessing(false);
  };

  return (
    <div className="min-h-screen bg-cream font-sans overflow-x-hidden">
      {/* Dynamic Background */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-honey/10 rounded-full blur-[120px] animate-pulse" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-honey/5 rounded-full blur-[100px]" />
      </div>

      <div className="max-w-5xl mx-auto px-12 py-16 relative z-10 space-y-20">
        <header className="flex items-center justify-between">
          <Link 
            href="/dashboard" 
            className="group flex items-center gap-4 text-[10px] font-bold uppercase tracking-[0.3em] text-bee-black/30 hover:text-bee-black transition-all"
          >
            <div className="w-8 h-8 rounded-full border border-wax flex items-center justify-center group-hover:bg-bee-black group-hover:text-white transition-all">
              <ArrowLeft className="w-3 h-3 group-hover:-translate-x-0.5 transition-transform" />
            </div>
            Back to Dashboard
          </Link>

          <div className="flex items-center gap-6">
            <div className="flex -space-x-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="w-8 h-8 rounded-full border-2 border-white bg-wax flex items-center justify-center text-[10px] font-bold text-bee-black/40">
                  U{i}
                </div>
              ))}
            </div>
            <div className="h-4 w-px bg-wax" />
            <div className="px-4 py-2 rounded-xl bg-white border border-wax shadow-sm flex items-center gap-3">
              <ShieldCheck className="w-4 h-4 text-green-500" />
              <span className="text-[10px] font-bold uppercase tracking-widest text-bee-black/40">Secure Node</span>
            </div>
          </div>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-20 items-stretch">
          <div className="lg:col-span-3 space-y-12">
            <div className="space-y-6">
              <motion.div
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-honey/10 border border-honey/20 text-honey-600 font-bold text-[9px] uppercase tracking-widest"
              >
                <Zap size={10} className="fill-honey-600" /> System: Knowledge Ingestion
              </motion.div>
              <h1 className="text-7xl font-display uppercase tracking-tighter leading-[0.8]">
                Synthesize <br />
                <span className="italic opacity-30 lowercase">Your Sources</span>
              </h1>
              <p className="text-bee-black/40 text-sm font-medium leading-relaxed max-w-sm">
                Feed your hive. Upload documents, audio, or video to transform raw data into a persistent knowledge graph.
              </p>
            </div>

            <div className="space-y-12">
              <ProjectSelector 
                selectedId={selectedProjectId} 
                onSelect={setSelectedProjectId} 
              />

              <div
                {...getRootProps()}
                className={cn(
                  "relative aspect-[16/10] bg-white border-2 border-dashed rounded-[3rem] transition-all duration-700 flex flex-col items-center justify-center gap-6 group overflow-hidden shadow-2xl shadow-honey/5",
                  isDragActive ? "border-honey bg-honey/5 scale-[0.98]" : "border-wax hover:border-honey/40 hover:bg-honey-50/10"
                )}
              >
                <input {...getInputProps()} />
                
                <div className={cn(
                  "p-8 bg-wax/10 rounded-[2.5rem] text-bee-black/20 transition-all duration-500 group-hover:scale-110 group-hover:rotate-12",
                  isDragActive && "bg-honey text-white rotate-12 scale-110 shadow-2xl shadow-honey/40"
                )}>
                  <Upload size={40} className={cn(isDragActive && "animate-bounce")} />
                </div>

                <div className="text-center space-y-2">
                  <p className="text-xl font-bold text-bee-black uppercase tracking-tight">Drop Assets Here</p>
                  <p className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-30">PDF, Media, Transcripts</p>
                </div>

                {/* Corner accents */}
                <div className="absolute top-8 left-8 w-8 h-8 border-t-2 border-l-2 border-wax group-hover:border-honey transition-colors" />
                <div className="absolute bottom-8 right-8 w-8 h-8 border-b-2 border-r-2 border-wax group-hover:border-honey transition-colors" />
                
                <AnimatePresence>
                  {isDragActive && (
                    <motion.div 
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="absolute inset-0 bg-honey/10 backdrop-blur-sm pointer-events-none"
                    />
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>

          <div className="lg:col-span-2 flex flex-col pt-8">
            <div className="flex-1 bg-white/60 backdrop-blur-3xl rounded-[3rem] border border-wax p-10 flex flex-col shadow-2xl">
              <div className="flex items-center justify-between mb-10">
                <h3 className="text-xs font-bold uppercase tracking-[0.2em] text-bee-black/40">Ingestion Flow</h3>
                <div className="px-3 py-1 bg-wax/20 rounded-full text-[8px] font-black uppercase tracking-widest">
                  {uploadQueue.length} Active
                </div>
              </div>

              <div className="flex-1 space-y-4 overflow-y-auto pr-2 scrollbar-none">
                <AnimatePresence mode="popLayout">
                  {uploadQueue.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-center space-y-4 opacity-20">
                      <Hexagon size={48} />
                      <p className="text-[10px] font-bold uppercase tracking-widest">Queue Empty</p>
                    </div>
                  ) : (
                    uploadQueue.map((item) => (
                      <motion.div
                        key={item.id}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        className="p-5 rounded-2xl bg-white border border-wax group hover:border-honey/40 transition-all flex items-center justify-between gap-4"
                      >
                        <div className="flex items-center gap-4 min-w-0">
                          <div className={cn(
                            "w-10 h-10 rounded-xl flex items-center justify-center transition-colors",
                            item.status === 'completed' ? "bg-green-50 text-green-500" : "bg-wax/20 text-bee-black/20"
                          )}>
                            {item.status === 'completed' ? <CheckCircle2 size={18} /> : 
                             item.status === 'uploading' || item.status === 'processing' ? <Loader2 size={18} className="animate-spin" /> :
                             <FileText size={18} />}
                          </div>
                          <div className="min-w-0">
                            <p className="text-xs font-bold text-bee-black truncate uppercase tracking-tight">{item.file.name}</p>
                            <p className="text-[9px] font-bold uppercase tracking-widest opacity-30 mt-0.5">
                              {item.status === 'uploading' ? 'Vaulting...' : 
                               item.status === 'processing' ? 'Synthesizing...' :
                               item.status === 'completed' ? 'Synchronized' : 'Queued'}
                            </p>
                          </div>
                        </div>
                      </motion.div>
                    ))
                  )}
                </AnimatePresence>
              </div>

              {uploadQueue.length > 0 && (
                <div className="mt-8 pt-8 border-t border-wax">
                  <button
                    onClick={startIngestion}
                    disabled={isProcessing || !selectedProjectId}
                    className={cn(
                      "w-full h-16 rounded-[1.5rem] font-bold uppercase tracking-[0.2em] text-xs transition-all flex items-center justify-center gap-3",
                      isProcessing || !selectedProjectId 
                        ? "bg-wax/20 text-bee-black/20 cursor-not-allowed" 
                        : "bg-bee-black text-white hover:bg-honey hover:text-bee-black shadow-xl"
                    )}
                  >
                    {isProcessing ? (
                      <>
                        <Loader2 size={16} className="animate-spin" />
                        Processing Hive
                      </>
                    ) : (
                      <>
                        Start Ingestion
                        <ChevronRight size={16} />
                      </>
                    )}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

