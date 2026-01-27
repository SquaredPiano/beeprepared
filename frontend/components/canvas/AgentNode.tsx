"use client";

import React from "react";
import { Handle, Position } from "@xyflow/react";
import { 
  Bot, 
  Search, 
  FileText, 
  GitBranch, 
  CheckCircle2, 
  Activity,
  Zap,
  Box
} from "lucide-react";
import { cn } from "@/lib/utils";

const agentIcons: Record<string, any> = {
  ingest: Box,
  extract: Search,
  categorize: GitBranch,
  generate: Zap,
  finalize: CheckCircle2,
};

import { motion } from "framer-motion";

export function AgentNode({ data }: { data: any }) {
  const Icon = agentIcons[data.type] || Bot;
  
  return (
    <motion.div
      initial={{ scale: 0.9, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      whileHover={{ scale: 1.02, y: -5 }}
      className={cn(
        "group relative min-w-[240px] glass-card p-8 rounded-[2.5rem] border-2 transition-all duration-500 cursor-grab active:cursor-grabbing",
        data.status === "processing" ? "border-honey-500 bg-honey-50/30 shadow-2xl shadow-honey-500/20" : "border-border/40 hover:border-honey-400"
      )}
    >
      {/* Connector Handles */}
      <Handle 
        type="target" 
        position={Position.Left} 
        className="!w-4 !h-4 !bg-honey-500 !border-4 !border-white !shadow-lg hover:!scale-125 transition-transform" 
      />
      <Handle 
        type="source" 
        position={Position.Right} 
        className="!w-4 !h-4 !bg-honey-500 !border-4 !border-white !shadow-lg hover:!scale-125 transition-transform" 
      />

      <div className="flex flex-col items-center gap-6 text-center">
        <div className={cn(
          "w-16 h-16 rounded-[1.5rem] flex items-center justify-center transition-all duration-700 relative overflow-hidden",
          data.status === "processing" ? "bg-honey-500 text-white shadow-xl shadow-honey-500/40" : "bg-muted group-hover:bg-honey-100 group-hover:text-honey-600"
        )}>
          <Icon className={cn("w-8 h-8 relative z-10", data.status === "processing" && "animate-pulse")} />
          {data.status === "processing" && (
            <motion.div
              className="absolute inset-0 bg-white/20"
              animate={{ x: ["-100%", "100%"] }}
              transition={{ repeat: Infinity, duration: 1.5, ease: "linear" }}
            />
          )}
        </div>
        
        <div className="space-y-2">
          <p className="text-[10px] font-bold uppercase tracking-[0.3em] opacity-40">{data.role || "Autonomous Agent"}</p>
          <h3 className="text-lg font-display font-bold uppercase tracking-tight">{data.label}</h3>
        </div>

        <div className={cn(
          "flex items-center gap-3 px-4 py-2 rounded-full text-[10px] font-bold uppercase tracking-widest transition-colors duration-500",
          data.status === "completed" ? "bg-green-50 text-green-700 border border-green-100" : 
          data.status === "processing" ? "bg-honey-500 text-white" : "bg-muted text-muted-foreground border border-transparent"
        )}>
          <Activity className={cn("w-3.5 h-3.5", data.status === "processing" && "animate-spin")} />
          {data.status || "idle"}
        </div>

        {data.description && (
          <p className="text-[10px] opacity-40 leading-relaxed max-w-[180px] font-medium">
            {data.description}
          </p>
        )}
      </div>

      {/* Connection Glow */}
      {data.status === "processing" && (
        <div className="absolute inset-0 rounded-[2.5rem] ring-8 ring-honey-500/10 animate-pulse pointer-events-none" />
      )}
    </motion.div>
  );
}
