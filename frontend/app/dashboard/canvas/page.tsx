"use client";

import { PipelineCanvas } from "@/components/canvas/PipelineCanvas";
import { AgentPalette } from "@/components/canvas/AgentPalette";
import { ArrowLeft, Plus, Edit3, Check } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, useState, Suspense } from "react";
import { useFlowStore } from "@/store/useFlowStore";

function CanvasHeader() {
  const searchParams = useSearchParams();
  const projectId = searchParams.get("id");
  const { loadProject, projectName, createNewProject } = useFlowStore();
  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setProjectName] = useState(projectName);

  useEffect(() => {
    if (projectId) {
      loadProject(projectId);
    } else {
      createNewProject();
    }
  }, [projectId]);

  useEffect(() => {
    setProjectName(projectName);
  }, [projectName]);

  const handleNameSave = () => {
    useFlowStore.setState({ projectName: tempName });
    setIsEditingName(false);
  };

  return (
    <header className="flex items-center justify-between px-8 py-6 border-b border-border/40 bg-white/50 backdrop-blur-md h-24 shrink-0">
      <div className="flex items-center gap-8">
        <Link 
          href="/dashboard/library" 
          className="group flex items-center gap-3 text-[10px] font-bold uppercase tracking-[0.2em] opacity-40 hover:opacity-100 transition-opacity cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Exit View
        </Link>
        <div className="h-4 w-px bg-border/60" />
        <div className="flex items-center gap-4">
          <div className="space-y-0.5">
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <input 
                  autoFocus
                  value={tempName}
                  onChange={(e) => setProjectName(e.target.value)}
                  onBlur={handleNameSave}
                  onKeyDown={(e) => e.key === "Enter" && handleNameSave()}
                  className="bg-transparent border-none focus:outline-none text-sm font-bold uppercase tracking-widest text-honey-600 w-48"
                />
                <Check size={14} className="text-honey-600" />
              </div>
            ) : (
              <div className="flex items-center gap-2 group cursor-pointer" onClick={() => setIsEditingName(true)}>
                <h1 className="text-sm font-bold uppercase tracking-widest">{projectName}</h1>
                <Edit3 size={12} className="opacity-0 group-hover:opacity-40 transition-opacity" />
              </div>
            )}
            <p className="text-[10px] opacity-40 uppercase tracking-tighter">
              {projectId ? "Stored in Hive" : "Interactive Visualization"}
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-4">
        <Link 
          href="/upload" 
          className="group flex items-center gap-4 bg-bee-black text-white pl-8 pr-6 py-4 rounded-2xl hover:bg-honey-500 transition-all cursor-pointer shadow-xl hover:scale-105 active:scale-95"
        >
          <span className="text-xs font-bold uppercase tracking-[0.2em]">Add Content</span>
          <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center group-hover:bg-bee-black/20 transition-colors">
            <Plus className="w-5 h-5" />
          </div>
        </Link>
      </div>
    </header>
  );
}

export default function CanvasPage() {
  return (
    <div className="flex flex-col h-screen bg-stone-50/30 overflow-hidden">
      <Suspense fallback={<div className="h-24 bg-white/50 animate-pulse" />}>
        <CanvasHeader />
      </Suspense>

      {/* Canvas Area */}
      <main className="flex-1 p-8 relative min-h-0 flex flex-col">
        <div className="absolute top-12 right-12 z-40 flex flex-col gap-4 items-end max-h-[calc(100vh-theme(spacing.40))] overflow-y-auto p-12 -m-12 scrollbar-hide pointer-events-none">
          <div className="pointer-events-auto">
            <AgentPalette />
          </div>
        </div>

        <motion.div 
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          className="flex-1 w-full h-full"
        >
          <PipelineCanvas />
        </motion.div>
      </main>
    </div>
  );
}

