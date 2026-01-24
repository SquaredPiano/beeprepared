"use client";

import React, { memo } from "react";
import { Handle, Position, NodeProps } from "@xyflow/react";
import { FileText, CheckCircle2, CircleDashed, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export const TaskNode = memo(({ data }: NodeProps) => {
  const status = data.status as string;
  
  const StatusIcon = {
    complete: CheckCircle2,
    processing: CircleDashed,
    pending: CircleDashed,
    failed: AlertCircle,
  }[status] || CircleDashed;

  return (
    <div className="group relative">
      <div className={cn(
        "px-6 py-4 bg-white border rounded-2xl shadow-sm min-w-[200px] transition-all duration-500 hover:shadow-xl hover:-translate-y-1 cursor-pointer",
        status === "complete" ? "border-green-100" : "border-border/60",
        status === "processing" && "border-honey-200"
      )}>
        <Handle
          type="target"
          position={Position.Left}
          className="!bg-border !w-2 !h-2 !border-0"
        />
        
        <div className="flex items-center gap-4">
          <div className={cn(
            "p-3 rounded-xl transition-colors",
            status === "complete" ? "bg-green-50 text-green-600" : "bg-muted text-muted-foreground",
            status === "processing" && "bg-honey-50 text-honey-600 animate-pulse"
          )}>
            <FileText className="w-5 h-5" />
          </div>
          
          <div className="flex-1 min-w-0">
            <h4 className="text-xs font-bold uppercase tracking-widest truncate">{data.label as string}</h4>
            <div className="flex items-center gap-1.5 mt-1">
              <StatusIcon className={cn(
                "w-3 h-3",
                status === "complete" ? "text-green-500" : "text-muted-foreground",
                status === "processing" && "text-honey-500 animate-spin"
              )} />
              <span className="text-[10px] font-medium opacity-40 uppercase tracking-tighter">
                {status}
              </span>
            </div>
          </div>
        </div>

        <Handle
          type="source"
          position={Position.Right}
          className="!bg-border !w-2 !h-2 !border-0"
        />
      </div>
      
      {/* Decorative Glow */}
      <div className={cn(
        "absolute -inset-2 rounded-3xl -z-10 opacity-0 group-hover:opacity-10 transition-opacity blur-xl",
        status === "complete" ? "bg-green-500" : "bg-honey-500"
      )} />
    </div>
  );
});

TaskNode.displayName = "TaskNode";
