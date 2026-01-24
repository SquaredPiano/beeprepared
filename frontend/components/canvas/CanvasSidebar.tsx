"use client";

import React, { useMemo } from "react";
import { motion } from "framer-motion";
import { 
  ChevronLeft, 
  ChevronRight, 
  Search, 
  Eraser, 
  Sparkles, 
  Layers, 
  HelpCircle, 
  FileText, 
  Presentation,
  Map,
  Share2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCanvasStore } from "@/store/useCanvasStore";
import { DraggableAgent } from "./DraggableAgent";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

const agents = [
  {
    type: 'process',
    subType: 'extraction',
    icon: Search,
    label: 'Extract',
    description: 'Extract content from source',
    color: 'blue' as const,
  },
  {
    type: 'process',
    subType: 'cleaning',
    icon: Eraser,
    label: 'Clean',
    description: 'Clean and normalize text',
    color: 'green' as const,
  },
  {
    type: 'process',
    subType: 'synthesis',
    icon: Sparkles,
    label: 'Synthesize',
    description: 'Generate knowledge core',
    color: 'purple' as const,
  },
  {
    type: 'result',
    subType: 'flashcards',
    icon: Layers,
    label: 'Flashcards',
    description: 'Generate study flashcards',
    color: 'honey' as const,
  },
  {
    type: 'result',
    subType: 'quiz',
    icon: HelpCircle,
    label: 'Quiz',
    description: 'Generate practice quiz',
    color: 'orange' as const,
  },
  {
    type: 'result',
    subType: 'exam',
    icon: FileText,
    label: 'Exam',
    description: 'Generate mock exam PDF',
    color: 'red' as const,
  },
  {
    type: 'result',
    subType: 'pptx',
    icon: Presentation,
    label: 'Slides',
    description: 'Generate presentation',
    color: 'indigo' as const,
  },
];

export function CanvasSidebar() {
  const { 
    isSidebarCollapsed, 
    setIsSidebarCollapsed, 
    nodes, 
    showMiniMap, 
    setShowMiniMap 
  } = useCanvasStore();

  const hasSource = useMemo(() => nodes.some(n => n.type === 'asset'), [nodes]);
  const hasProcess = useMemo(() => nodes.some(n => n.type === 'process'), [nodes]);

  return (
    <motion.aside
      initial={false}
      animate={{ width: isSidebarCollapsed ? 80 : 320 }}
      className="absolute left-0 top-0 bottom-0 z-[55] bg-white/80 backdrop-blur-xl border-r border-wax flex flex-col shadow-sm transition-all"
    >
      <div className="flex items-center justify-between p-6 border-b border-wax h-[100px] shrink-0">
        {!isSidebarCollapsed && (
          <div className="flex flex-col">
            <h2 className="font-display text-xs uppercase tracking-[0.2em] font-bold text-bee-black">
              AI Agents
            </h2>
            <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-bee-black/30 mt-1">
              Architecture Palette
            </p>
          </div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
          className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer ml-auto"
        >
          {isSidebarCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 custom-scrollbar">
        {!isSidebarCollapsed && (
          <div className="px-2 py-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-bee-black/20">
              Logic Layers
            </p>
          </div>
        )}
        
        {agents.slice(0, 3).map((agent) => (
          <DraggableAgent 
            key={agent.subType}
            {...agent}
            collapsed={isSidebarCollapsed}
            disabled={agent.type === 'process' && !hasSource}
            tooltip={agent.type === 'process' && !hasSource ? "Ingest an asset first" : undefined}
          />
        ))}

        <Separator className="bg-wax/50 my-6" />

        {!isSidebarCollapsed && (
          <div className="px-2 py-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-bee-black/20">
              Artifact Synthesis
            </p>
          </div>
        )}

        {agents.slice(3).map((agent) => (
          <DraggableAgent 
            key={agent.subType}
            {...agent}
            collapsed={isSidebarCollapsed}
            disabled={agent.type === 'result' && !hasProcess}
            tooltip={agent.type === 'result' && !hasProcess ? "Add a synthesis layer first" : undefined}
          />
        ))}
      </div>

      <div className="p-6 border-t border-wax bg-white/50 shrink-0 space-y-4">
        <div className="flex items-center justify-between">
          {!isSidebarCollapsed && (
            <span className="text-[10px] font-bold uppercase tracking-widest text-bee-black/40 flex items-center gap-2">
              <Map size={14} /> Mini-map
            </span>
          )}
          <Switch 
            checked={showMiniMap} 
            onCheckedChange={setShowMiniMap}
            className="data-[state=checked]:bg-honey"
          />
        </div>
        
        {!isSidebarCollapsed && (
          <Button 
            variant="outline" 
            className="w-full h-12 rounded-2xl border-wax font-display text-[10px] font-bold uppercase tracking-widest hover:bg-honey hover:border-honey transition-all cursor-pointer"
          >
            <Share2 size={14} className="mr-2" /> Share Canvas
          </Button>
        )}
      </div>
    </motion.aside>
  );
}
