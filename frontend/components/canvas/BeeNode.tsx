"use client";

import React from "react";
import { Handle, Position } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";
import { motion } from "framer-motion";

interface BeeNodeProps {
  data: {
    label: string;
    description?: string;
    icon: LucideIcon;
    status?: "pending" | "processing" | "completed";
    beeType?: string;
  };
  selected?: boolean;
}

export function BeeNode({ data, selected }: BeeNodeProps) {
  const Icon = data.icon;

  return (
    <div className={cn(
      "group relative px-8 py-6 rounded-3xl border bg-white shadow-sm transition-all duration-700 overflow-hidden",
      selected ? "border-honey-500 ring-8 ring-honey-500/5 shadow-2xl scale-105" : "border-border/40 hover:border-honey-300 hover:shadow-xl",
      data.status === "processing" && "border-honey-500 shadow-honey-500/10"
    )}>
      <Handle type="target" position={Position.Left} className="!bg-honey-300 !w-4 !h-4 !border-4 !border-white !-left-2" />
      
      {/* Processing shimmer */}
      {data.status === "processing" && (
        <motion.div 
          className="absolute inset-0 bg-gradient-to-r from-transparent via-honey-500/10 to-transparent"
          animate={{ x: ['-100%', '100%'] }}
          transition={{ duration: 1.5, repeat: Infinity, ease: 'linear' }}
        />
      )}

      <div className="flex items-center gap-6 relative z-10">
        <div className={cn(
          "w-16 h-16 rounded-2xl flex items-center justify-center transition-all duration-700",
          data.status === "completed" ? "bg-green-50 text-green-600 rotate-12" : 
          data.status === "processing" ? "bg-honey-500 text-white scale-110 shadow-lg shadow-honey-500/40" : "bg-stone-50 text-muted-foreground group-hover:bg-honey-50 group-hover:text-honey-600"
        )}>
          <Icon className={cn("w-8 h-8", data.status === "processing" && "animate-pulse")} strokeWidth={1.5} />
        </div>
        
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <div className="text-sm font-display uppercase tracking-widest font-bold">
              {data.label}
            </div>
            {data.beeType && (
              <span className="text-[10px] px-2 py-0.5 bg-honey-100 text-honey-700 rounded-full font-bold uppercase tracking-tighter">
                {data.beeType}
              </span>
            )}
          </div>
          {data.description && (
            <div className="text-[10px] text-muted-foreground font-bold uppercase tracking-widest opacity-40 leading-none">
              {data.description}
            </div>
          )}
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-honey-300 !w-4 !h-4 !border-4 !border-white !-right-2" />
      
      {/* Background icon decoration */}
      <Icon className="absolute -bottom-4 -right-4 w-24 h-24 opacity-[0.02] -rotate-12 pointer-events-none" />
    </div>
  );
}
