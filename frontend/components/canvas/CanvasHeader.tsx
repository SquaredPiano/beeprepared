"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  ChevronUp, 
  ChevronDown, 
  ArrowLeft, 
  Save, 
  Hexagon,
  Share2,
  MoreVertical
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCanvasStore } from "@/store/useCanvasStore";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

export function CanvasHeader() {
  const { 
    projectName, 
    setProjectName, 
    save, 
    isSaving, 
    isHeaderCollapsed, 
    setIsHeaderCollapsed 
  } = useCanvasStore();
  
  const [isEditing, setIsEditing] = useState(false);

  return (
    <motion.header
      initial={false}
      animate={{ height: isHeaderCollapsed ? 64 : 100 }}
      className="absolute top-0 left-0 right-0 z-[60] bg-white/80 backdrop-blur-xl border-b border-wax flex items-center px-8 shadow-sm transition-all"
    >
      <div className="flex-1 flex items-center gap-8">
        <Link 
          href="/dashboard"
          className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] text-bee-black/40 hover:text-bee-black transition-colors"
        >
          <ArrowLeft size={14} />
          Exit Hive
        </Link>

        <div className="flex items-center gap-4 flex-1">
          <div className="w-10 h-10 rounded-xl bg-honey/10 flex items-center justify-center border border-honey/20">
            <Hexagon size={20} className="text-honey-600 fill-honey-600/20" />
          </div>
          
          <div className="flex flex-col min-w-0">
            {isEditing ? (
              <Input
                autoFocus
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                onBlur={() => setIsEditing(false)}
                onKeyDown={(e) => e.key === 'Enter' && setIsEditing(false)}
                className="h-8 font-display text-xl uppercase tracking-tighter bg-transparent border-none p-0 focus-visible:ring-0"
              />
            ) : (
              <h1 
                onClick={() => setIsEditing(true)}
                className="font-display text-xl uppercase tracking-tighter text-bee-black cursor-pointer hover:text-honey-600 transition-colors truncate"
              >
                {projectName || "Untitled Pipeline"}
              </h1>
            )}
            {!isHeaderCollapsed && (
              <p className="text-[9px] font-bold uppercase tracking-[0.3em] text-bee-black/30">
                Architectural Visualization Workspace
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {!isHeaderCollapsed && (
          <>
            <Button 
              variant="ghost" 
              size="sm" 
              className="h-10 px-4 rounded-xl text-bee-black/60 hover:bg-honey/10 cursor-pointer"
            >
              <Share2 size={16} className="mr-2" /> Share
            </Button>
            <div className="w-px h-6 bg-wax" />
          </>
        )}
        
        <Button 
          onClick={save}
          disabled={isSaving}
          className={cn(
            "h-10 px-6 rounded-xl font-display text-[10px] font-bold uppercase tracking-widest transition-all cursor-pointer shadow-lg",
            isSaving ? "bg-honey/50" : "bg-honey hover:bg-honey-600 text-bee-black"
          )}
        >
          <Save size={14} className={cn("mr-2", isSaving && "animate-pulse")} />
          {isSaving ? "Persisting..." : "Persist Architecture"}
        </Button>

        <button
          onClick={() => setIsHeaderCollapsed(!isHeaderCollapsed)}
          className="w-10 h-10 rounded-full hover:bg-bee-black/5 flex items-center justify-center transition-all cursor-pointer ml-2"
        >
          {isHeaderCollapsed ? <ChevronDown size={18} /> : <ChevronUp size={18} />}
        </button>
      </div>
    </motion.header>
  );
}
