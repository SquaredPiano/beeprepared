"use client";

import { BeeCanvas } from "@/components/canvas/BeeCanvas";
import { ArrowLeft, Edit3, Check, Hexagon } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";

function CanvasHeader() {
  const searchParams = useSearchParams();
  const projectId = searchParams.get("id");
  const [projectName, setProjectName] = useState("Unstructured Pipeline");
  const [isEditingName, setIsEditingName] = useState(false);

  return (
    <header className="flex items-center justify-between px-8 py-6 border-b border-wax bg-white/80 backdrop-blur-xl h-24 shrink-0 z-50">
      <div className="flex items-center gap-8">
        <Link 
          href="/dashboard/library" 
          className="group flex items-center gap-3 text-[10px] font-bold uppercase tracking-[0.2em] text-bee-black/40 hover:text-bee-black transition-all cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Exit Hive
        </Link>
        <div className="h-4 w-px bg-wax" />
        <div className="flex items-center gap-4">
          <div className="p-2 bg-honey/10 rounded-lg">
            <Hexagon className="w-5 h-5 text-honey fill-honey/20" />
          </div>
          <div className="space-y-0.5">
            {isEditingName ? (
              <div className="flex items-center gap-2">
                <input 
                  autoFocus
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  onBlur={() => setIsEditingName(false)}
                  onKeyDown={(e) => e.key === "Enter" && setIsEditingName(false)}
                  className="bg-transparent border-none focus:outline-none text-sm font-bold uppercase tracking-widest text-honey outline-none"
                />
                <Check size={14} className="text-honey" />
              </div>
            ) : (
              <div className="flex items-center gap-2 group cursor-pointer" onClick={() => setIsEditingName(true)}>
                <h1 className="text-sm font-bold uppercase tracking-widest text-bee-black">{projectName}</h1>
                <Edit3 size={12} className="opacity-0 group-hover:opacity-40 transition-opacity text-bee-black" />
              </div>
            )}
            <p className="text-[10px] text-bee-black/40 uppercase tracking-[0.1em] font-medium">
              {projectId ? `Project ID: ${projectId.slice(0, 8)}` : "Editing workspace"}
            </p>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-6">
        <div className="flex -space-x-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="w-8 h-8 rounded-full border-2 border-white bg-wax flex items-center justify-center text-[10px] font-bold text-bee-black/40">
              U{i}
            </div>
          ))}
        </div>
        <div className="h-4 w-px bg-wax" />
        <div className="text-right">
          <p className="text-[10px] font-bold text-honey uppercase tracking-wider">Status</p>
          <p className="text-xs font-bold text-bee-black">Ready</p>
        </div>
      </div>
    </header>
  );
}

export default function CanvasPage() {
  return (
    <div className="flex flex-col h-screen bg-cream overflow-hidden font-sans">
      {/* Canvas Area */}
      <main className="flex-1 relative min-h-0">
        <motion.div 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, ease: "easeOut" }}
          className="w-full h-full"
        >
          <BeeCanvas />
        </motion.div>
      </main>
    </div>
  );
}
