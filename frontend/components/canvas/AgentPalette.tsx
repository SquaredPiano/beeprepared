"use client";

import { motion } from "framer-motion";
import { 
  Box, 
  Search, 
  GitBranch, 
  Zap, 
  CheckCircle2,
  Bot
} from "lucide-react";
import { playSound } from "@/lib/sounds";

export function AgentPalette() {
  const agents = [
    { type: "ingest", icon: Box, label: "Forager", role: "Input Gateway", description: "Collects and validates input files", color: "bg-blue-500" },
    { type: "extract", icon: Search, label: "Structural", role: "Structural Analyst", description: "Extracts core architectural data", color: "bg-green-500" },
    { type: "categorize", icon: GitBranch, label: "Cognitive", role: "Matrix Manager", description: "Organizes data into neural nodes", color: "bg-purple-500" },
    { type: "generate", icon: Zap, label: "Synthesis", role: "Content Creator", description: "Generates high-fidelity study artifacts", color: "bg-orange-500" },
    { type: "finalize", icon: CheckCircle2, label: "Archival", role: "Library Manager", description: "Finalizes and stores the knowledge", color: "bg-gray-500" },
  ];

  const onDragStart = (event: React.DragEvent, agent: any) => {
    event.dataTransfer.setData("application/reactflow", JSON.stringify(agent));
    event.dataTransfer.effectAllowed = "move";
    playSound("pickup");
  };

  return (
    <div className="fixed left-32 top-32 glass p-8 rounded-[2.5rem] shadow-2xl border border-border/40 z-40 w-72 space-y-8">
      <div className="space-y-1">
        <h3 className="text-xs font-bold uppercase tracking-[0.3em] opacity-40">Agent Palette</h3>
        <p className="text-[10px] font-medium opacity-20">Drag into hive to scale</p>
      </div>
      
      <div className="space-y-4">
        {agents.map((agent) => {
          const Icon = agent.icon;
          return (
            <motion.div
              key={agent.type}
              draggable
              onDragStart={(e) => onDragStart(e, agent)}
              whileHover={{ scale: 1.02, x: 5 }}
              whileTap={{ scale: 0.98 }}
              onMouseEnter={() => playSound("hover")}
              className="flex items-center gap-4 p-4 glass-card rounded-2xl cursor-grab active:cursor-grabbing group hover:border-honey-500/50"
            >
              <div className={`w-12 h-12 rounded-xl ${agent.color} text-white flex items-center justify-center shadow-lg group-hover:scale-110 transition-transform`}>
                <Icon size={20} />
              </div>
              <div className="space-y-0.5">
                <span className="text-[10px] font-bold uppercase tracking-widest block">{agent.label}</span>
                <span className="text-[8px] font-bold opacity-30 uppercase tracking-tighter block">{agent.role}</span>
              </div>
            </motion.div>
          );
        })}
      </div>
      
      <div className="pt-4 border-t border-border/40">
        <div className="flex items-center gap-3 text-[9px] font-bold opacity-30 uppercase tracking-widest">
           <Bot size={14} />
           <span>Hive Capacity: 84%</span>
        </div>
      </div>
    </div>
  );
}
