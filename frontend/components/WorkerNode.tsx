"use client";

import React, { memo } from "react";
import { Handle, Position } from "@xyflow/react";
import { motion } from "framer-motion";
import { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface WorkerNodeData {
  label: string;
  icon: LucideIcon;
  status: "idle" | "processing" | "completed";
  description: string;
}

export const WorkerNode = memo(({ data }: { data: WorkerNodeData }) => {
  const Icon = data.icon;

  return (
    <div className="relative group">
      <div className={cn(
        "relative w-64 p-5 glass rounded-2xl border-2 transition-all duration-500",
        data.status === "processing" ? "border-honey-500 honey-glow ring-4 ring-honey-500/10" : "border-border/40"
      )}>
        <Handle
          type="target"
          position={Position.Left}
          className="!w-3 !h-3 !bg-honey-500 !border-2 !border-background"
        />
        
        <div className="flex items-center gap-4">
          <div className={cn(
            "p-3 rounded-xl transition-colors duration-500",
            data.status === "processing" ? "bg-honey-500 text-white" : "bg-muted text-muted-foreground"
          )}>
            <Icon className="w-5 h-5" />
          </div>
          <div className="flex-1">
            <h3 className="font-display text-sm font-bold uppercase tracking-tight">{data.label}</h3>
            <p className="text-[10px] uppercase tracking-widest opacity-60 mt-0.5">{data.description}</p>
          </div>
        </div>

        {data.status === "processing" && (
          <div className="mt-4 space-y-2">
            <div className="flex justify-between text-[10px] uppercase tracking-widest font-bold text-honey-600">
              <span>Buzzing...</span>
              <span>75%</span>
            </div>
            <div className="w-full bg-honey-100 h-1 rounded-full overflow-hidden">
              <motion.div
                className="bg-honey-500 h-full"
                initial={{ width: "0%" }}
                animate={{ width: "75%" }}
                transition={{ duration: 1, repeat: Infinity, repeatType: "reverse" }}
              />
            </div>
          </div>
        )}

        <Handle
          type="source"
          position={Position.Right}
          className="!w-3 !h-3 !bg-honey-500 !border-2 !border-background"
        />
      </div>

      {/* Hive background decoration */}
      <div className="absolute -z-10 -top-2 -right-2 opacity-5 group-hover:opacity-10 transition-opacity">
        <svg width="40" height="40" viewBox="0 0 40 40" fill="currentColor">
          <path d="M20 0l17.32 10v20L20 40 2.68 30V10z" />
        </svg>
      </div>
    </div>
  );
});

WorkerNode.displayName = "WorkerNode";
